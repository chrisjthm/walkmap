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
) -> ScoringResult:
    """Score a segment based on OSM tags and nearby POIs."""
    weights = factor_weights.get("weights", factor_weights)
    thresholds = factor_weights.get("thresholds", {})

    score = 40.0
    factors: dict[str, float] = {}

    highway = osm_tags.get("highway")
    if _tag_in(highway, {"footway", "path", "residential", "living_street", "pedestrian"}):
        contribution = weights.get("road_type_positive", 0.0)
        factors["road_type_positive"] = contribution
        score += contribution
    if _tag_in(highway, {"motorway", "trunk", "primary"}):
        contribution = weights.get("road_type_negative", 0.0)
        factors["road_type_negative"] = contribution
        score += contribution

    sidewalk = osm_tags.get("sidewalk")
    if _tag_in(sidewalk, {"both", "left", "right", "yes"}):
        contribution = weights.get("sidewalk_positive", 0.0)
        factors["sidewalk_positive"] = contribution
        score += contribution
    if _tag_in(sidewalk, {"no"}):
        contribution = weights.get("sidewalk_negative", 0.0)
        factors["sidewalk_negative"] = contribution
        score += contribution

    surface = osm_tags.get("surface")
    if _tag_in(surface, {"paved", "asphalt", "cobblestone", "paving_stones"}):
        contribution = weights.get("surface_positive", 0.0)
        factors["surface_positive"] = contribution
        score += contribution
    if _tag_in(surface, {"dirt", "gravel", "sand", "ground", "mud"}):
        contribution = weights.get("surface_negative", 0.0)
        factors["surface_negative"] = contribution
        score += contribution

    if _has_tree_cover(osm_tags, nearby_pois):
        contribution = weights.get("tree_cover", 0.0)
        factors["tree_cover"] = contribution
        score += contribution

    waterfront_distance = _waterfront_distance_m(osm_tags, nearby_pois, water_distance_m)
    waterfront_bonus, waterfront_factor = _waterfront_bonus(
        waterfront_distance, weights.get("waterfront", 0.0)
    )
    if waterfront_bonus:
        factors["waterfront"] = waterfront_bonus
        score += waterfront_bonus

    business_count = _business_poi_count(nearby_pois)
    business_bonus = _poi_density_bonus(business_count)
    if business_bonus:
        factors["business_density"] = business_bonus
        score += business_bonus

    park_distance = _park_distance_m(osm_tags, nearby_pois, park_distance_m)
    park_bonus = _park_bonus(park_distance)
    if park_bonus:
        factors["park_adjacency"] = park_bonus
        score += park_bonus

    if _is_industrial(osm_tags, nearby_pois):
        contribution = weights.get("industrial_landuse", 0.0)
        factors["industrial_landuse"] = contribution
        score += contribution

    if _is_residential(osm_tags):
        contribution = weights.get("residential_landuse", 0.0)
        factors["residential_landuse"] = contribution
        score += contribution

    residential_refinement = _residential_refinement_modifier(osm_tags)
    if residential_refinement:
        factors["residential_refinement"] = residential_refinement
        score += residential_refinement

    maxspeed_limit = thresholds.get("speed_limit_mph", 45)
    if _maxspeed_over(osm_tags.get("maxspeed"), maxspeed_limit):
        contribution = weights.get("speed_limit", 0.0)
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

    score = max(0.0, min(100.0, score))
    confidence = _confidence_score(osm_tags, nearby_pois)

    return ScoringResult(score=score, confidence=confidence, factors=factors)


def update_composite_score(ai_score: float, user_ratings: list[bool]) -> CompositeScore:
    """Blend AI score with user ratings per the spec formula."""
    rating_count = len(user_ratings)
    if rating_count == 0:
        return CompositeScore(
            composite_score=ai_score,
            verified=False,
            user_score=None,
            rating_count=0,
        )

    user_score = compute_user_score(user_ratings)
    if rating_count < 5:
        composite = (ai_score * (5 - rating_count) + user_score * rating_count) / 5
        return CompositeScore(
            composite_score=composite,
            verified=True,
            user_score=user_score,
            rating_count=rating_count,
        )

    return CompositeScore(
        composite_score=user_score,
        verified=True,
        user_score=user_score,
        rating_count=rating_count,
    )


def compute_user_score(ratings: list[bool], prior: float = 50.0, prior_weight: int = 2) -> float:
    """Compute a user score with a prior applied only to low sample sizes."""
    thumbs_up = sum(1 for rating in ratings if rating)
    total = len(ratings)
    if total == 0:
        return prior
    raw_score = thumbs_up / total * 100.0
    if total < 5:
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


def _waterfront_bonus(distance_m: float | None, weight: float) -> tuple[float, float]:
    if distance_m is None:
        return 0.0, 0.0
    if distance_m <= 40:
        factor = 1.0
    elif distance_m <= 80:
        factor = 0.4
    elif distance_m <= 150:
        factor = 0.16
    else:
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


def _poi_density_bonus(business_count: int) -> float:
    if business_count <= 0:
        return 0.0
    if business_count <= 3:
        return 8.0
    if business_count <= 8:
        return 16.0
    return 22.0


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


def _park_bonus(distance_m: float | None) -> float:
    if distance_m is None:
        return 0.0
    if distance_m <= 20:
        return 18.0
    if distance_m <= 75:
        return 10.0
    if distance_m <= 150:
        return 4.0
    return 0.0


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


def _residential_refinement_modifier(osm_tags: dict) -> float:
    highway = osm_tags.get("highway")
    penalties: list[float] = []
    bonuses: list[float] = []

    if _tag_in(highway, {"living_street"}):
        bonuses.append(10.0)

    if _tag_in(highway, {"residential", "living_street"}):
        if _tag_in(osm_tags.get("oneway"), {"yes", "true", "1"}):
            penalties.append(-8.0)
        if _maxspeed_over_residential(osm_tags.get("maxspeed")):
            penalties.append(-10.0)
        if _lanes_at_least(osm_tags.get("lanes"), 2):
            penalties.append(-8.0)

    if _tag_in(highway, {"secondary", "tertiary"}) and "sidewalk" not in osm_tags:
        penalties.append(-12.0)

    penalty_total = max(-20.0, sum(penalties))
    bonus_total = min(10.0, sum(bonuses))
    return penalty_total + bonus_total


def _maxspeed_over_residential(maxspeed: Any) -> bool:
    if maxspeed is None:
        return False
    for value in _tag_values(maxspeed):
        if isinstance(value, (int, float)):
            if value > 25:
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
            if speed > 40:
                return True
        else:
            if speed > 25:
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


def _confidence_score(osm_tags: dict, nearby_pois: list[dict]) -> float:
    tag_count = len(osm_tags)
    poi_count = len(nearby_pois)

    confidence = 0.2
    confidence += min(tag_count, 8) * 0.05
    confidence += min(poi_count, 10) * 0.02
    if "highway" in osm_tags:
        confidence += 0.1

    if tag_count < 3:
        confidence = min(confidence, 0.35)

    return max(0.0, min(1.0, confidence))
