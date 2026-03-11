from __future__ import annotations

from app.scoring import load_scoring_config, score_segment, update_composite_score


def test_score_motorway_is_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "motorway"}, [], weights)
    assert result.score < 30


def test_waterfront_footway_scores_high() -> None:
    weights = load_scoring_config()
    result = score_segment(
        {"highway": "footway", "sidewalk": "both"},
        [{"natural": "water"}],
        weights,
    )
    assert result.score > 70
    assert result.factors.get("road_type_positive") == 1.0
    assert result.factors.get("sidewalk_positive") == 1.0
    assert result.factors.get("waterfront") == 1.0


def test_residential_sidewalk_and_business_scores_above_threshold() -> None:
    weights = load_scoring_config()
    pois = [{"amenity": "restaurant"} for _ in range(5)]
    result = score_segment(
        {"highway": "residential", "sidewalk": "both"},
        pois,
        weights,
    )
    assert result.score > 55


def test_low_tag_count_confidence_is_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "residential"}, [], weights)
    assert result.confidence < 0.4


def test_surface_positive_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"surface": "asphalt"}, [], weights)
    assert result.factors.get("surface_positive") == 1.0


def test_surface_negative_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"surface": "gravel"}, [], weights)
    assert result.factors.get("surface_negative") == 1.0


def test_tree_cover_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"natural": "tree_row"}, [], weights)
    assert result.factors.get("tree_cover") == 1.0


def test_park_adjacency_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({}, [{"leisure": "park"}], weights)
    assert result.factors.get("park_adjacency") == 1.0


def test_industrial_landuse_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"landuse": "industrial"}, [], weights)
    assert result.factors.get("industrial_landuse") == 1.0


def test_residential_landuse_factor() -> None:
    weights = load_scoring_config()
    result = score_segment(
        {"landuse": "residential", "highway": "residential"},
        [],
        weights,
    )
    assert result.factors.get("residential_landuse") == 1.0


def test_speed_limit_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"maxspeed": "50 mph"}, [], weights)
    assert result.factors.get("speed_limit") == 1.0


def test_sidewalk_negative_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"sidewalk": "no"}, [], weights)
    assert result.factors.get("sidewalk_negative") == 1.0


def test_update_composite_score_no_ratings() -> None:
    result = update_composite_score(ai_score=60, user_ratings=[])
    assert result.composite_score == 60
    assert result.verified is False


def test_update_composite_score_blend_for_few_ratings() -> None:
    result = update_composite_score(ai_score=60, user_ratings=[True, True, True])
    assert result.verified is True
    assert 60 < result.composite_score < 100


def test_update_composite_score_user_only_for_many_ratings() -> None:
    result = update_composite_score(ai_score=60, user_ratings=[True] * 6)
    assert result.verified is True
    assert result.composite_score >= 95


def test_weight_change_affects_score() -> None:
    weights = load_scoring_config()
    baseline = score_segment({"highway": "footway"}, [], weights).score
    weights["weights"]["road_type_positive"] = 5.0
    modified = score_segment({"highway": "footway"}, [], weights).score
    assert baseline != modified
