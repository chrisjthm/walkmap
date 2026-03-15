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
    tiers = weights["waterfront"]["distance_tiers"]
    base = score_segment({"highway": "footway"}, [], weights).score

    close = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=tiers[0]["max_distance_m"],
    )
    assert close.factors.get("waterfront") == (
        weights["weights"]["waterfront"] * tiers[0]["multiplier"]
    )
    assert close.score == (
        base + weights["weights"]["waterfront"] * tiers[0]["multiplier"]
    )

    mid = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=tiers[1]["max_distance_m"],
    )
    expected_mid = (
        base + weights["weights"]["waterfront"] * tiers[1]["multiplier"]
    )
    assert abs(mid.score - expected_mid) < 0.01
    assert mid.factors.get("waterfront") == (
        weights["weights"]["waterfront"] * tiers[1]["multiplier"]
    )

    far = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=tiers[2]["max_distance_m"],
    )
    expected_far = (
        base + weights["weights"]["waterfront"] * tiers[2]["multiplier"]
    )
    assert abs(far.score - expected_far) < 0.01
    assert far.factors.get("waterfront") == (
        weights["weights"]["waterfront"] * tiers[2]["multiplier"]
    )

    none = score_segment(
        {"highway": "footway"},
        [],
        weights,
        water_distance_m=tiers[-1]["max_distance_m"] + 50,
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
    score_base = weights["score"]["base"]
    expected_bonus = (
        weights["weights"]["road_type_positive"] + weights["weights"]["sidewalk_positive"]
    )
    expected_bonus += weights["poi_density"]["tiers"][1]["bonus"]
    assert result.score > score_base + expected_bonus - 0.01


def test_poi_density_bonus_tiers() -> None:
    weights = load_scoring_config()
    tiers = weights["poi_density"]["tiers"]
    base = score_segment({}, [], weights).score

    low_count = tiers[0]["max_count"]
    mid_count = tiers[1]["max_count"]
    high_count = mid_count + 5

    low = score_segment(
        {}, [{"amenity": "restaurant"} for _ in range(low_count)], weights
    ).score
    mid = score_segment(
        {}, [{"amenity": "restaurant"} for _ in range(mid_count)], weights
    ).score
    high = score_segment(
        {}, [{"amenity": "restaurant"} for _ in range(high_count)], weights
    ).score

    assert low - base == tiers[0]["bonus"]
    assert mid - base == tiers[1]["bonus"]
    assert high - base == weights["poi_density"]["default_bonus"]


def test_low_tag_count_confidence_is_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "residential"}, [], weights)
    assert result.confidence <= weights["confidence"]["low_tag_cap"]


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


def test_park_adjacency_distance_bands() -> None:
    weights = load_scoring_config()
    tiers = weights["park_adjacency"]["tiers"]
    base = score_segment({}, [], weights).score

    close = score_segment({}, [], weights, park_distance_m=tiers[0]["max_distance_m"])
    assert close.score == base + tiers[0]["bonus"]
    assert close.factors.get("park_adjacency") == tiers[0]["bonus"]

    mid = score_segment({}, [], weights, park_distance_m=tiers[1]["max_distance_m"])
    assert mid.score == base + tiers[1]["bonus"]
    assert mid.factors.get("park_adjacency") == tiers[1]["bonus"]

    far = score_segment({}, [], weights, park_distance_m=tiers[2]["max_distance_m"])
    assert far.score == base + tiers[2]["bonus"]
    assert far.factors.get("park_adjacency") == tiers[2]["bonus"]

    none = score_segment(
        {}, [], weights, park_distance_m=tiers[-1]["max_distance_m"] + 50
    )
    assert none.score == base
    assert none.factors.get("park_adjacency") is None


def test_intersection_density_modifier_by_distance() -> None:
    weights = load_scoring_config()
    bands = weights["intersection_density"]["bands"]
    base = score_segment({}, [], weights).score

    very_short = score_segment({}, [], weights, distance_m=bands[0]["max_distance_m"])
    assert very_short.score == base + bands[0]["modifier"]
    assert very_short.factors.get("intersection_density") == bands[0]["modifier"]

    short = score_segment({}, [], weights, distance_m=bands[1]["max_distance_m"])
    assert short.score == base + bands[1]["modifier"]
    assert short.factors.get("intersection_density") == bands[1]["modifier"]

    typical = score_segment({}, [], weights, distance_m=bands[2]["max_distance_m"])
    assert typical.score == base
    assert typical.factors.get("intersection_density") is None

    long_block = score_segment({}, [], weights, distance_m=bands[3]["max_distance_m"])
    assert long_block.score == base + bands[3]["modifier"]
    assert long_block.factors.get("intersection_density") == bands[3]["modifier"]

    very_long = score_segment(
        {}, [], weights, distance_m=bands[-1]["max_distance_m"] + 100
    )
    assert very_long.score == base + weights["intersection_density"]["above_max_modifier"]
    assert (
        very_long.factors.get("intersection_density")
        == weights["intersection_density"]["above_max_modifier"]
    )


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
    assert round(baseline - penalized, 1) == abs(
        weights["residential_refinement"]["oneway_penalty"]
    )


def test_living_street_bonus() -> None:
    weights = load_scoring_config()
    residential = score_segment({"highway": "residential"}, [], weights).score
    living = score_segment({"highway": "living_street"}, [], weights).score
    assert (
        living - residential >= weights["residential_refinement"]["living_street_bonus"]
    )


def test_secondary_no_sidewalk_penalty_keeps_score_low() -> None:
    weights = load_scoring_config()
    result = score_segment({"highway": "secondary", "lanes": "2"}, [], weights)
    assert result.score < weights["score"]["base"]


def test_residential_penalty_stack_capped() -> None:
    weights = load_scoring_config()
    baseline = score_segment({"highway": "residential"}, [], weights).score
    penalized = score_segment(
        {"highway": "residential", "oneway": "yes", "maxspeed": "45 mph"},
        [],
        weights,
    ).score
    expected = abs(weights["residential_refinement"]["oneway_penalty"]) + abs(
        weights["residential_refinement"]["maxspeed_penalty"]
    )
    assert round(baseline - penalized, 1) == expected
