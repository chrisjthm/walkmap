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
    assert result.factors.get("road_type_positive") == weights["weights"]["road_type_positive"]
    assert result.factors.get("sidewalk_positive") == weights["weights"]["sidewalk_positive"]
    assert result.factors.get("waterfront") == weights["weights"]["waterfront"]


def test_waterfront_distance_tiers_apply_bonus() -> None:
    weights = load_scoring_config()
    base = score_segment({"highway": "footway"}, [], weights).score

    close = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=30,
    )
    assert close.factors.get("waterfront") == weights["weights"]["waterfront"]
    assert close.score == base + weights["weights"]["waterfront"]

    mid = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=60,
    )
    expected_mid = base + weights["weights"]["waterfront"] * 0.4
    assert abs(mid.score - expected_mid) < 0.01
    assert mid.factors.get("waterfront") == weights["weights"]["waterfront"] * 0.4

    far = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=120,
    )
    expected_far = base + weights["weights"]["waterfront"] * 0.16
    assert abs(far.score - expected_far) < 0.01
    assert far.factors.get("waterfront") == weights["weights"]["waterfront"] * 0.16

    none = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=200,
    )
    assert none.factors.get("waterfront") is None
    assert none.score == base


def test_residential_sidewalk_and_business_scores_above_threshold() -> None:
    weights = load_scoring_config()
    pois = [{"amenity": "restaurant"} for _ in range(5)]
    result = score_segment(
        {"highway": "residential", "sidewalk": "both"},
        pois,
        weights,
    )
    assert result.score > 55


def test_poi_density_bonus_tiers() -> None:
    weights = load_scoring_config()
    base = score_segment({}, [], weights).score

    low = score_segment({}, [{"amenity": "restaurant"} for _ in range(2)], weights).score
    mid = score_segment({}, [{"amenity": "restaurant"} for _ in range(6)], weights).score
    high = score_segment({}, [{"amenity": "restaurant"} for _ in range(15)], weights).score

    assert low - base == 8.0
    assert mid - base == 16.0
    assert high - base == 22.0


def test_low_tag_count_confidence_is_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "residential"}, [], weights)
    assert result.confidence < 0.4


def test_surface_positive_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"surface": "asphalt"}, [], weights)
    assert result.factors.get("surface_positive") == weights["weights"]["surface_positive"]


def test_surface_negative_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"surface": "gravel"}, [], weights)
    assert result.factors.get("surface_negative") == weights["weights"]["surface_negative"]


def test_tree_cover_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"natural": "tree_row"}, [], weights)
    assert result.factors.get("tree_cover") == weights["weights"]["tree_cover"]


def test_park_adjacency_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({}, [{"leisure": "park"}], weights)
    assert result.factors.get("park_adjacency") == weights["weights"]["park_adjacency"]


def test_industrial_landuse_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"landuse": "industrial"}, [], weights)
    assert result.factors.get("industrial_landuse") == weights["weights"]["industrial_landuse"]


def test_residential_landuse_factor() -> None:
    weights = load_scoring_config()
    result = score_segment(
        {"landuse": "residential", "highway": "residential"},
        [],
        weights,
    )
    assert result.factors.get("residential_landuse") == weights["weights"]["residential_landuse"]


def test_speed_limit_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"maxspeed": "50 mph"}, [], weights)
    assert result.factors.get("speed_limit") == weights["weights"]["speed_limit"]


def test_sidewalk_negative_factor() -> None:
    weights = load_scoring_config()
    result = score_segment({"sidewalk": "no"}, [], weights)
    assert result.factors.get("sidewalk_negative") == weights["weights"]["sidewalk_negative"]


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


def test_walkmap_sidewalk_penalty_applies() -> None:
    weights = load_scoring_config()
    baseline = score_segment({"highway": "residential"}, [], weights).score
    penalized = score_segment(
        {"highway": "residential", "walkmap_sidewalk_penalty": -15.0},
        [],
        weights,
    )
    assert penalized.score < baseline
    assert penalized.factors.get("walkmap_sidewalk_penalty") == -15.0


def test_residential_oneway_penalty() -> None:
    weights = load_scoring_config()
    baseline = score_segment({"highway": "residential"}, [], weights).score
    penalized = score_segment({"highway": "residential", "oneway": "yes"}, [], weights).score
    assert round(baseline - penalized, 1) == 8.0


def test_living_street_bonus() -> None:
    weights = load_scoring_config()
    residential = score_segment({"highway": "residential"}, [], weights).score
    living = score_segment({"highway": "living_street"}, [], weights).score
    assert living - residential >= 10.0


def test_secondary_no_sidewalk_penalty_keeps_score_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "secondary", "lanes": "2"}, [], weights)
    assert result.score < 40.0


def test_residential_penalty_stack_capped() -> None:
    weights = load_scoring_config()
    baseline = score_segment({"highway": "residential"}, [], weights).score
    penalized = score_segment(
        {"highway": "residential", "oneway": "yes", "maxspeed": "45 mph"},
        [],
        weights,
    ).score
    assert round(baseline - penalized, 1) == 18.0
