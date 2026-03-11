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
) -> ScoringResult:
    """Score a segment based on OSM tags and nearby POIs."""
    weights = factor_weights.get("weights", factor_weights)
    thresholds = factor_weights.get("thresholds", {})

    score = 50.0
    factors: dict[str, float] = {}

    highway = osm_tags.get("highway")
    if highway in {"footway", "path", "residential", "living_street", "pedestrian"}:
        factors["road_type_positive"] = 1.0
        score += weights.get("road_type_positive", 0.0)
    if highway in {"motorway", "trunk", "primary"}:
        factors["road_type_negative"] = 1.0
        score += weights.get("road_type_negative", 0.0)

    sidewalk = osm_tags.get("sidewalk")
    if sidewalk in {"both", "left", "right", "yes"}:
        factors["sidewalk_positive"] = 1.0
        score += weights.get("sidewalk_positive", 0.0)
    if sidewalk == "no":
        factors["sidewalk_negative"] = 1.0
        score += weights.get("sidewalk_negative", 0.0)

    surface = osm_tags.get("surface")
    if surface in {"paved", "asphalt", "cobblestone", "paving_stones"}:
        factors["surface_positive"] = 1.0
        score += weights.get("surface_positive", 0.0)
    if surface in {"dirt", "gravel", "sand", "ground", "mud"}:
        factors["surface_negative"] = 1.0
        score += weights.get("surface_negative", 0.0)

    if _has_tree_cover(osm_tags, nearby_pois):
        factors["tree_cover"] = 1.0
        score += weights.get("tree_cover", 0.0)

    if _is_waterfront(osm_tags, nearby_pois):
        factors["waterfront"] = 1.0
        score += weights.get("waterfront", 0.0)

    business_count = _business_poi_count(nearby_pois)
    business_threshold = thresholds.get("business_density", 5)
    business_score = min(business_count / float(business_threshold), 1.0)
    if business_score > 0:
        factors["business_density"] = business_score
        score += weights.get("business_density", 0.0) * business_score

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


def _has_tree_cover(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("natural") == "tree_row":
        return True
    return any(poi.get("natural") == "tree_row" for poi in nearby_pois)


def _is_waterfront(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("natural") == "water" or osm_tags.get("waterway"):
        return True
    return any(poi.get("natural") == "water" or poi.get("waterway") for poi in nearby_pois)


def _business_poi_count(nearby_pois: list[dict]) -> int:
    business_amenities = {
        "restaurant",
        "cafe",
        "bar",
        "fast_food",
        "biergarten",
    }
    count = 0
    for poi in nearby_pois:
        amenity = poi.get("amenity")
        shop = poi.get("shop")
        if amenity in business_amenities or shop is not None:
            count += 1
    return count


def _is_park_adjacent(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    if osm_tags.get("leisure") == "park":
        return True
    return any(poi.get("leisure") == "park" for poi in nearby_pois)


def _is_industrial(osm_tags: dict, nearby_pois: list[dict]) -> bool:
    industrial_tags = {"industrial", "commercial", "parking", "warehouse"}
    landuse = osm_tags.get("landuse")
    if landuse in industrial_tags:
        return True
    return any(poi.get("landuse") in industrial_tags for poi in nearby_pois)


def _is_residential(osm_tags: dict) -> bool:
    landuse = osm_tags.get("landuse")
    highway = osm_tags.get("highway")
    return landuse == "residential" and highway in {"residential", "living_street"}


def _maxspeed_over(maxspeed: Any, limit: int) -> bool:
    if maxspeed is None:
        return False
    if isinstance(maxspeed, (int, float)):
        return maxspeed > limit
    if isinstance(maxspeed, str):
        digits = "".join(ch for ch in maxspeed if ch.isdigit())
        if digits:
            try:
                return int(digits) > limit
            except ValueError:
                return False
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
