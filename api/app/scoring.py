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
) -> ScoringResult:
    """Score a segment based on OSM tags and nearby POIs."""
    weights = factor_weights.get("weights", factor_weights)
    thresholds = factor_weights.get("thresholds", {})

    score = 50.0
    factors: dict[str, float] = {}

    highway = osm_tags.get("highway")
    if _tag_in(highway, {"footway", "path", "residential", "living_street", "pedestrian"}):
        factors["road_type_positive"] = 1.0
        score += weights.get("road_type_positive", 0.0)
    if _tag_in(highway, {"motorway", "trunk", "primary"}):
        factors["road_type_negative"] = 1.0
        score += weights.get("road_type_negative", 0.0)

    sidewalk = osm_tags.get("sidewalk")
    if _tag_in(sidewalk, {"both", "left", "right", "yes"}):
        factors["sidewalk_positive"] = 1.0
        score += weights.get("sidewalk_positive", 0.0)
    if _tag_in(sidewalk, {"no"}):
        factors["sidewalk_negative"] = 1.0
        score += weights.get("sidewalk_negative", 0.0)

    surface = osm_tags.get("surface")
    if _tag_in(surface, {"paved", "asphalt", "cobblestone", "paving_stones"}):
        factors["surface_positive"] = 1.0
        score += weights.get("surface_positive", 0.0)
    if _tag_in(surface, {"dirt", "gravel", "sand", "ground", "mud"}):
        factors["surface_negative"] = 1.0
        score += weights.get("surface_negative", 0.0)

    if _has_tree_cover(osm_tags, nearby_pois):
        factors["tree_cover"] = 1.0
        score += weights.get("tree_cover", 0.0)

    waterfront_distance = _waterfront_distance_m(osm_tags, nearby_pois, water_distance_m)
    waterfront_bonus, waterfront_factor = _waterfront_bonus(
        waterfront_distance, weights.get("waterfront", 0.0)
    )
    if waterfront_bonus:
        factors["waterfront"] = waterfront_factor
        score += waterfront_bonus

    business_count = _business_poi_count(nearby_pois)
    business_bonus = _poi_density_bonus(business_count)
    if business_bonus:
        factors["business_density"] = business_bonus
        score += business_bonus

    if _is_park_adjacent(osm_tags, nearby_pois):
        factors["park_adjacency"] = 1.0
        score += weights.get("park_adjacency", 0.0)

    if _is_industrial(osm_tags, nearby_pois):
        factors["industrial_landuse"] = 1.0
        score += weights.get("industrial_landuse", 0.0)

    if _is_residential(osm_tags):
        factors["residential_landuse"] = 1.0
        score += weights.get("residential_landuse", 0.0)

    maxspeed_limit = thresholds.get("speed_limit_mph", 45)
    if _maxspeed_over(osm_tags.get("maxspeed"), maxspeed_limit):
        factors["speed_limit"] = 1.0
        score += weights.get("speed_limit", 0.0)

    adjustment_raw = osm_tags.get("walkmap_score_adjustment")
    if adjustment_raw is not None:
        try:
            adjustment = float(adjustment_raw)
        except (TypeError, ValueError):
            adjustment = 0.0
        if adjustment:
            factors["walkmap_score_adjustment"] = adjustment
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


def _is_park_adjacent(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("leisure") == "park":
        return True
    return any(poi.get("leisure") == "park" for poi in nearby_pois)


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
