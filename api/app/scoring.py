from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("scoring_config.yml")


@dataclass(frozen=True)
class ScoringResult:
    score: float
    confidence: float
    factors: dict[str, float]


@dataclass(frozen=True)
class CompositeScore:
    composite_score: float
    verified: bool
    user_score: float | None
    rating_count: int


def load_scoring_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load scoring weights and thresholds from YAML."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def score_segment(
    osm_tags: dict,
    nearby_pois: list[dict],
    factor_weights: dict,
    water_distance_m: float | None = None,
    park_distance_m: float | None = None,
    distance_m: float | None = None,
) -> ScoringResult:
    """Score a segment based on OSM tags and nearby POIs."""
    config = factor_weights
    weights = config["weights"]
    thresholds = config["thresholds"]
    score_config = config["score"]

    score = score_config["base"]
    factors: dict[str, float] = {}

    highway = osm_tags.get("highway")
    if _tag_in(highway, {"footway", "path", "residential", "living_street", "pedestrian"}):
        contribution = weights["road_type_positive"]
        factors["road_type_positive"] = contribution
        score += contribution
    if _tag_in(highway, {"motorway", "trunk", "primary"}):
        contribution = weights["road_type_negative"]
        factors["road_type_negative"] = contribution
        score += contribution

    sidewalk = osm_tags.get("sidewalk")
    if _tag_in(sidewalk, {"both", "left", "right", "yes"}):
        contribution = weights["sidewalk_positive"]
        factors["sidewalk_positive"] = contribution
        score += contribution
    if _tag_in(sidewalk, {"no"}):
        contribution = weights["sidewalk_negative"]
        factors["sidewalk_negative"] = contribution
        score += contribution

    surface = osm_tags.get("surface")
    if _tag_in(surface, {"paved", "asphalt", "cobblestone", "paving_stones"}):
        contribution = weights["surface_positive"]
        factors["surface_positive"] = contribution
        score += contribution
    if _tag_in(surface, {"dirt", "gravel", "sand", "ground", "mud"}):
        contribution = weights["surface_negative"]
        factors["surface_negative"] = contribution
        score += contribution

    if _has_tree_cover(osm_tags, nearby_pois):
        contribution = weights["tree_cover"]
        factors["tree_cover"] = contribution
        score += contribution

    waterfront_distance = _waterfront_distance_m(osm_tags, nearby_pois, water_distance_m)
    waterfront_bonus, waterfront_factor = _waterfront_bonus(
        waterfront_distance, weights["waterfront"], config["waterfront"]
    )
    if waterfront_bonus:
        factors["waterfront"] = waterfront_bonus
        score += waterfront_bonus

    business_count = _business_poi_count(nearby_pois)
    business_bonus = _poi_density_bonus(business_count, config["poi_density"])
    if business_bonus:
        factors["business_density"] = business_bonus
        score += business_bonus

    park_distance = _park_distance_m(osm_tags, nearby_pois, park_distance_m)
    park_bonus = _park_bonus(park_distance, config["park_adjacency"])
    if park_bonus:
        factors["park_adjacency"] = park_bonus
        score += park_bonus

    intersection_modifier = _intersection_density_modifier(distance_m, config["intersection_density"])
    if intersection_modifier:
        factors["intersection_density"] = intersection_modifier
        score += intersection_modifier

    if _is_industrial(osm_tags, nearby_pois):
        contribution = weights["industrial_landuse"]
        factors["industrial_landuse"] = contribution
        score += contribution

    if _is_residential(osm_tags):
        contribution = weights["residential_landuse"]
        factors["residential_landuse"] = contribution
        score += contribution

    residential_refinement = _residential_refinement_modifier(
        osm_tags, config["residential_refinement"]
    )
    if residential_refinement:
        factors["residential_refinement"] = residential_refinement
        score += residential_refinement

    maxspeed_limit = thresholds["speed_limit_mph"]
    if _maxspeed_over(osm_tags.get("maxspeed"), maxspeed_limit):
        contribution = weights["speed_limit"]
        factors["speed_limit"] = contribution
        score += contribution

    adjustment_raw = osm_tags.get("walkmap_sidewalk_penalty")
    if adjustment_raw is not None:
        try:
            adjustment = float(adjustment_raw)
        except (TypeError, ValueError):
            adjustment = 0.0
        if adjustment:
            factors["walkmap_sidewalk_penalty"] = adjustment
            score += adjustment

    score = max(score_config["min"], min(score_config["max"], score))
    confidence = _confidence_score(osm_tags, nearby_pois, config["confidence"])

    return ScoringResult(score=score, confidence=confidence, factors=factors)


def update_composite_score(
    ai_score: float,
    user_ratings: list[bool],
    scoring_config: dict[str, Any] | None = None,
) -> CompositeScore:
    """Blend AI score with user ratings per the spec formula."""
    config = scoring_config or load_scoring_config()
    composite_config = config["composite"]
    rating_count = len(user_ratings)
    if rating_count == 0:
        return CompositeScore(
            composite_score=ai_score,
            verified=False,
            user_score=None,
            rating_count=0,
        )

    user_score = compute_user_score(user_ratings, composite_config)
    if rating_count < composite_config["blend_window"]:
        composite = (
            ai_score * (composite_config["blend_window"] - rating_count)
            + user_score * rating_count
        ) / composite_config["blend_window"]
        return CompositeScore(
            composite_score=composite,
            verified=True,
            user_score=user_score,
            rating_count=rating_count,
        )

    if rating_count >= composite_config["user_only_min_ratings"]:
        return CompositeScore(
            composite_score=user_score,
            verified=True,
            user_score=user_score,
            rating_count=rating_count,
        )

    composite = (
        ai_score * (composite_config["blend_window"] - rating_count)
        + user_score * rating_count
    ) / composite_config["blend_window"]
    return CompositeScore(
        composite_score=composite,
        verified=True,
        user_score=user_score,
        rating_count=rating_count,
    )


def compute_user_score(ratings: list[bool], composite_config: dict[str, Any]) -> float:
    """Compute a user score with a prior applied only to low sample sizes."""
    prior = composite_config["prior_score"]
    prior_weight = composite_config["prior_weight"]
    thumbs_up = sum(1 for rating in ratings if rating)
    total = len(ratings)
    if total == 0:
        return prior
    raw_score = thumbs_up / total * composite_config["score_scale"]
    if total < composite_config["user_only_min_ratings"]:
        return (raw_score * total + prior_weight * prior) / (total + prior_weight)
    return raw_score


def _tag_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _tag_in(value: Any, options: set[str]) -> bool:
    return any(tag in options for tag in _tag_values(value))


def _has_tree_cover(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("natural") == "tree_row":
        return True
    return any(poi.get("natural") == "tree_row" for poi in nearby_pois)


def _is_waterfront(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("natural") == "water" or osm_tags.get("waterway"):
        return True
    if osm_tags.get("leisure") == "marina":
        return True
    return any(
        poi.get("natural") == "water" or poi.get("waterway") or poi.get("leisure") == "marina"
        for poi in nearby_pois
    )


def _waterfront_distance_m(
    osm_tags: dict, nearby_pois: list[dict], water_distance_m: float | None
) -> float | None:
    if _is_waterfront(osm_tags, nearby_pois):
        return 0.0
    if water_distance_m is not None:
        return float(water_distance_m)
    distances: list[float] = []
    for poi in nearby_pois:
        if not (
            poi.get("natural") == "water"
            or poi.get("waterway")
            or poi.get("leisure") == "marina"
        ):
            continue
        distance = poi.get("distance_m")
        if distance is None:
            distances.append(0.0)
            continue
        try:
            distances.append(float(distance))
        except (TypeError, ValueError):
            continue
    if not distances:
        return None
    return min(distances)


def _waterfront_bonus(
    distance_m: float | None, weight: float, waterfront_config: dict[str, Any]
) -> tuple[float, float]:
    if distance_m is None:
        return 0.0, 0.0
    factor = 0.0
    for tier in waterfront_config["distance_tiers"]:
        if distance_m <= tier["max_distance_m"]:
            factor = tier["multiplier"]
            break
    if factor == 0.0:
        return 0.0, 0.0
    return weight * factor, factor


def _business_poi_count(nearby_pois: list[dict]) -> int:
    count = 0
    for poi in nearby_pois:
        amenity = poi.get("amenity")
        shop = poi.get("shop")
        if amenity is not None or shop is not None:
            count += 1
    return count


def _poi_density_bonus(business_count: int, poi_config: dict[str, Any]) -> float:
    if business_count <= 0:
        return 0.0
    for tier in poi_config["tiers"]:
        if business_count <= tier["max_count"]:
            return tier["bonus"]
    return poi_config["default_bonus"]


def _is_park_poi(tags: dict) -> bool:
    return tags.get("leisure") in {"park", "playground"} or tags.get("landuse") == "grass"


def _park_distance_m(
    osm_tags: dict, nearby_pois: list[dict], park_distance_m: float | None
) -> float | None:
    if _is_park_poi(osm_tags):
        return 0.0
    if park_distance_m is not None:
        return float(park_distance_m)
    distances: list[float] = []
    for poi in nearby_pois:
        if not _is_park_poi(poi):
            continue
        distance = poi.get("distance_m")
        if distance is None:
            distances.append(0.0)
            continue
        try:
            distances.append(float(distance))
        except (TypeError, ValueError):
            continue
    if not distances:
        return None
    return min(distances)


def _park_bonus(distance_m: float | None, park_config: dict[str, Any]) -> float:
    if distance_m is None:
        return 0.0
    for tier in park_config["tiers"]:
        if distance_m <= tier["max_distance_m"]:
            return tier["bonus"]
    return 0.0


def _intersection_density_modifier(
    distance_m: float | None, intersection_config: dict[str, Any]
) -> float:
    if distance_m is None:
        return 0.0
    try:
        value = float(distance_m)
    except (TypeError, ValueError):
        return 0.0
    for band in intersection_config["bands"]:
        if value <= band["max_distance_m"]:
            return band["modifier"]
    return intersection_config["above_max_modifier"]


def _is_industrial(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    industrial_tags = {"industrial", "commercial", "parking", "warehouse"}
    landuse = osm_tags.get("landuse")
    if _tag_in(landuse, industrial_tags):
        return True
    return any(poi.get("landuse") in industrial_tags for poi in nearby_pois)


def _is_residential(osm_tags: dict) -> bool:
    landuse = osm_tags.get("landuse")
    highway = osm_tags.get("highway")
    return _tag_in(landuse, {"residential"}) and _tag_in(
        highway, {"residential", "living_street"}
    )


def _maxspeed_over(maxspeed: Any, limit: int) -> bool:
    if maxspeed is None:
        return False
    for value in _tag_values(maxspeed):
        if isinstance(value, (int, float)):
            if value > limit:
                return True
            continue
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if digits:
            try:
                if int(digits) > limit:
                    return True
            except ValueError:
                continue
    return False


def _residential_refinement_modifier(
    osm_tags: dict, refinement_config: dict[str, Any]
) -> float:
    highway = osm_tags.get("highway")
    penalties: list[float] = []
    bonuses: list[float] = []

    if _tag_in(highway, {"living_street"}):
        bonuses.append(refinement_config["living_street_bonus"])

    if _tag_in(highway, {"residential", "living_street"}):
        if _tag_in(osm_tags.get("oneway"), {"yes", "true", "1"}):
            penalties.append(refinement_config["oneway_penalty"])
        if _maxspeed_over_residential(
            osm_tags.get("maxspeed"), refinement_config
        ):
            penalties.append(refinement_config["maxspeed_penalty"])
        if _lanes_at_least(osm_tags.get("lanes"), refinement_config["lanes_minimum"]):
            penalties.append(refinement_config["lanes_penalty"])

    if _tag_in(highway, {"secondary", "tertiary"}) and "sidewalk" not in osm_tags:
        penalties.append(refinement_config["secondary_no_sidewalk_penalty"])

    penalty_total = max(refinement_config["penalty_cap"], sum(penalties))
    bonus_total = min(refinement_config["bonus_cap"], sum(bonuses))
    return penalty_total + bonus_total


def _maxspeed_over_residential(maxspeed: Any, refinement_config: dict[str, Any]) -> bool:
    if maxspeed is None:
        return False
    for value in _tag_values(maxspeed):
        if isinstance(value, (int, float)):
            if value > refinement_config["maxspeed_residential_mph"]:
                return True
            continue
        text = str(value).lower().strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            continue
        try:
            speed = int(digits)
        except ValueError:
            continue
        if "km" in text or "kph" in text or "kmh" in text:
            if speed > refinement_config["maxspeed_residential_kph"]:
                return True
        else:
            if speed > refinement_config["maxspeed_residential_mph"]:
                return True
    return False


def _lanes_at_least(lanes: Any, minimum: int) -> bool:
    if lanes is None:
        return False
    for value in _tag_values(lanes):
        if isinstance(value, (int, float)):
            if value >= minimum:
                return True
            continue
        digits = []
        current = ""
        for ch in str(value):
            if ch.isdigit():
                current += ch
            else:
                if current:
                    digits.append(current)
                    current = ""
        if current:
            digits.append(current)
        for entry in digits:
            try:
                if int(entry) >= minimum:
                    return True
            except ValueError:
                continue
    return False


def _confidence_score(
    osm_tags: dict, nearby_pois: list[dict], confidence_config: dict[str, Any]
) -> float:
    tag_count = len(osm_tags)
    poi_count = len(nearby_pois)

    confidence = confidence_config["base"]
    confidence += min(tag_count, confidence_config["tag_cap"]) * confidence_config["tag_weight"]
    confidence += min(poi_count, confidence_config["poi_cap"]) * confidence_config["poi_weight"]
    if "highway" in osm_tags:
        confidence += confidence_config["highway_bonus"]

    if tag_count < confidence_config["low_tag_threshold"]:
        confidence = min(confidence, confidence_config["low_tag_cap"])

    return max(confidence_config["min"], min(confidence_config["max"], confidence))
