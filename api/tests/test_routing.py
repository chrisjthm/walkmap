from __future__ import annotations

import json

from sqlalchemy import text

from app.routing import Coordinate, suggest_loop_routes, suggest_point_to_point_routes
from app.routing_graph import refresh_graph


def _insert_segment(
    db_connection,
    segment_id: str,
    wkt: str,
    *,
    composite_score: float,
    verified: bool = True,
    ai_confidence: float | None = None,
    osm_tags: dict | None = None,
) -> None:
    db_connection.execute(
        text(
            """
            INSERT INTO segments (
                id,
                geometry,
                osm_tags,
                ai_score,
                ai_confidence,
                composite_score,
                verified,
                rating_count,
                vibe_tag_counts
            )
            VALUES (
                :id,
                ST_GeomFromText(:wkt, 4326),
                CAST(:osm_tags AS jsonb),
                :ai_score,
                :ai_confidence,
                :composite_score,
                :verified,
                0,
                '{}'::jsonb
            )
            """
        ),
        {
            "id": segment_id,
            "wkt": wkt,
            "osm_tags": json.dumps(osm_tags or {"highway": "footway"}),
            "ai_score": composite_score,
            "ai_confidence": ai_confidence,
            "composite_score": composite_score,
            "verified": verified,
        },
    )


def _insert_poi(db_connection, poi_id: str, wkt: str, *, osm_tags: dict | None = None) -> None:
    db_connection.execute(
        text(
            """
            INSERT INTO pois (
                id,
                name,
                geometry,
                osm_tags
            )
            VALUES (
                :id,
                :name,
                ST_GeomFromText(:wkt, 4326),
                CAST(:osm_tags AS jsonb)
            )
            """
        ),
        {
            "id": poi_id,
            "name": (osm_tags or {}).get("name"),
            "wkt": wkt,
            "osm_tags": json.dumps(osm_tags or {"amenity": "restaurant"}),
        },
    )


def _build_three_corridor_graph(db_connection) -> None:
    _insert_segment(
        db_connection,
        "1:1:2:0",
        "LINESTRING(-74.0000 40.0000, -74.0010 40.0000)",
        composite_score=96.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_segment(
        db_connection,
        "2:2:3:0",
        "LINESTRING(-74.0010 40.0000, -74.0020 40.0000)",
        composite_score=94.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_segment(
        db_connection,
        "3:1:4:0",
        "LINESTRING(-74.0000 40.0000, -74.0010 40.0010)",
        composite_score=70.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "4:4:3:0",
        "LINESTRING(-74.0010 40.0010, -74.0020 40.0000)",
        composite_score=68.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "5:1:5:0",
        "LINESTRING(-74.0000 40.0000, -74.0010 39.9990)",
        composite_score=40.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "6:5:3:0",
        "LINESTRING(-74.0010 39.9990, -74.0020 40.0000)",
        composite_score=35.0,
        osm_tags={"highway": "footway"},
    )
    _insert_poi(db_connection, "poi-dining-1", "POINT(-74.0005 40.0005)")
    _insert_poi(db_connection, "poi-dining-2", "POINT(-74.0015 40.0005)")


def _build_priority_mode_graph(db_connection) -> None:
    _insert_segment(
        db_connection,
        "20:20:21:0",
        "LINESTRING(-74.0200 40.0200, -74.0210 40.0200)",
        composite_score=95.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "21:21:22:0",
        "LINESTRING(-74.0210 40.0200, -74.0220 40.0200)",
        composite_score=93.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "22:20:23:0",
        "LINESTRING(-74.0200 40.0200, -74.0210 40.0210)",
        composite_score=70.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_segment(
        db_connection,
        "23:23:22:0",
        "LINESTRING(-74.0210 40.0210, -74.0220 40.0200)",
        composite_score=68.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_poi(db_connection, "poi-priority-1", "POINT(-74.0204 40.0200)")
    _insert_poi(db_connection, "poi-priority-2", "POINT(-74.0216 40.0200)")


def _build_loop_graph(db_connection) -> None:
    loop_segments = [
        (
            "40:1:2:0",
            "LINESTRING(-74.0500 40.0500, -74.0500 40.0530)",
            92.0,
        ),
        (
            "41:2:3:0",
            "LINESTRING(-74.0500 40.0530, -74.0465 40.0515)",
            91.0,
        ),
        (
            "42:3:1:0",
            "LINESTRING(-74.0465 40.0515, -74.0500 40.0500)",
            90.0,
        ),
        (
            "43:1:4:0",
            "LINESTRING(-74.0500 40.0500, -74.0460 40.0500)",
            84.0,
        ),
        (
            "44:4:5:0",
            "LINESTRING(-74.0460 40.0500, -74.0475 40.0465)",
            83.0,
        ),
        (
            "45:5:1:0",
            "LINESTRING(-74.0475 40.0465, -74.0500 40.0500)",
            82.0,
        ),
        (
            "46:1:6:0",
            "LINESTRING(-74.0500 40.0500, -74.0500 40.0470)",
            76.0,
        ),
        (
            "47:6:7:0",
            "LINESTRING(-74.0500 40.0470, -74.0535 40.0485)",
            75.0,
        ),
        (
            "48:7:1:0",
            "LINESTRING(-74.0535 40.0485, -74.0500 40.0500)",
            74.0,
        ),
    ]
    for segment_id, wkt, composite_score in loop_segments:
        _insert_segment(
            db_connection,
            segment_id,
            wkt,
            composite_score=composite_score,
            osm_tags={"highway": "footway"},
        )


def _jaccard_similarity(first: set[str], second: set[str]) -> float:
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def test_point_to_point_routes_return_low_overlap_candidates(db_connection) -> None:
    _build_three_corridor_graph(db_connection)
    refresh_graph(connection=db_connection)

    routes = suggest_point_to_point_routes(
        Coordinate(lat=40.00002, lng=-74.00002),
        Coordinate(lat=40.00001, lng=-74.00201),
    )

    assert len(routes) >= 2
    for route in routes:
        assert route.segment_ids
        assert route.distance_m > 0
        assert route.avg_score > 0

    assert set(routes[0].segment_ids) == {"1:1:2:0", "2:2:3:0"}
    assert _jaccard_similarity(set(routes[0].segment_ids), set(routes[1].segment_ids)) < 0.5


def test_priority_modes_shift_route_selection(db_connection) -> None:
    _build_priority_mode_graph(db_connection)
    refresh_graph(connection=db_connection)

    highest_rated = suggest_point_to_point_routes(
        Coordinate(lat=40.02002, lng=-74.02002),
        Coordinate(lat=40.02001, lng=-74.02201),
        priority="highest-rated",
        candidate_count=1,
    )[0]
    residential = suggest_point_to_point_routes(
        Coordinate(lat=40.02002, lng=-74.02002),
        Coordinate(lat=40.02001, lng=-74.02201),
        priority="residential",
        candidate_count=1,
    )[0]
    dining = suggest_point_to_point_routes(
        Coordinate(lat=40.02002, lng=-74.02002),
        Coordinate(lat=40.02001, lng=-74.02201),
        priority="dining",
        candidate_count=1,
    )[0]

    assert set(highest_rated.segment_ids) == {"20:20:21:0", "21:21:22:0"}
    assert set(residential.segment_ids) == {"22:20:23:0", "23:23:22:0"}
    assert set(dining.segment_ids) == {"20:20:21:0", "21:21:22:0"}
    assert highest_rated.segment_ids != residential.segment_ids
    assert dining.avg_restaurant_distance_m is not None
    assert residential.avg_restaurant_distance_m is not None
    assert dining.avg_restaurant_distance_m < residential.avg_restaurant_distance_m
    assert dining.avg_score - residential.avg_score > 10.0


def test_residential_priority_prefers_residential_highways_without_landuse(db_connection) -> None:
    _insert_segment(
        db_connection,
        "30:30:31:0",
        "LINESTRING(-74.0300 40.0300, -74.0310 40.0300)",
        composite_score=75.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "31:31:32:0",
        "LINESTRING(-74.0310 40.0300, -74.0320 40.0300)",
        composite_score=74.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "32:30:33:0",
        "LINESTRING(-74.0300 40.0300, -74.0310 40.0310)",
        composite_score=55.0,
        osm_tags={"highway": "residential"},
    )
    _insert_segment(
        db_connection,
        "33:33:32:0",
        "LINESTRING(-74.0310 40.0310, -74.0320 40.0300)",
        composite_score=54.0,
        osm_tags={"highway": "residential"},
    )
    refresh_graph(connection=db_connection)

    residential = suggest_point_to_point_routes(
        Coordinate(lat=40.03002, lng=-74.03002),
        Coordinate(lat=40.03001, lng=-74.03201),
        priority="residential",
        candidate_count=1,
    )[0]

    assert set(residential.segment_ids) == {"32:30:33:0", "33:33:32:0"}


def test_origin_equal_destination_returns_empty_routes(db_connection) -> None:
    _build_three_corridor_graph(db_connection)
    refresh_graph(connection=db_connection)

    routes = suggest_point_to_point_routes(
        Coordinate(lat=40.0000, lng=-74.0000),
        Coordinate(lat=40.0000, lng=-74.0000),
    )

    assert routes == []


def test_ocean_coordinate_snaps_to_nearest_land_node(db_connection) -> None:
    _build_three_corridor_graph(db_connection)
    refresh_graph(connection=db_connection)

    routes = suggest_point_to_point_routes(
        Coordinate(lat=39.9000, lng=-74.5000),
        Coordinate(lat=40.00001, lng=-74.00201),
        candidate_count=1,
    )

    assert len(routes) == 1
    assert 39.999 <= routes[0].snapped_start.lat <= 40.0
    assert -74.002 <= routes[0].snapped_start.lng <= -74.0


def test_routing_excludes_non_pedestrian_edges(db_connection) -> None:
    _insert_segment(
        db_connection,
        "10:10:11:0",
        "LINESTRING(-74.0100 40.0100, -74.0110 40.0100)",
        composite_score=99.0,
        osm_tags={"highway": "primary"},
    )
    _insert_segment(
        db_connection,
        "11:10:12:0",
        "LINESTRING(-74.0100 40.0100, -74.0105 40.0105)",
        composite_score=60.0,
        osm_tags={"highway": "footway"},
    )
    _insert_segment(
        db_connection,
        "12:12:11:0",
        "LINESTRING(-74.0105 40.0105, -74.0110 40.0100)",
        composite_score=60.0,
        osm_tags={"highway": "footway"},
    )
    refresh_graph(connection=db_connection)

    routes = suggest_point_to_point_routes(
        Coordinate(lat=40.0100, lng=-74.0100),
        Coordinate(lat=40.0100, lng=-74.0110),
        candidate_count=1,
    )

    assert len(routes) == 1
    assert routes[0].segment_ids == ["11:10:12:0", "12:12:11:0"]


def test_loop_routes_return_closed_low_overlap_candidates(db_connection) -> None:
    _build_loop_graph(db_connection)
    refresh_graph(connection=db_connection)

    routes = suggest_loop_routes(
        Coordinate(lat=40.05001, lng=-74.05001),
        distance_m=1000.0,
    )

    assert len(routes) >= 2
    for route in routes:
        assert route.segment_ids
        assert route.node_ids[0] == route.node_ids[-1]
        assert len(route.segment_ids) == len(set(route.segment_ids))
        assert abs(route.distance_m - 1000.0) <= 150.0

    assert _jaccard_similarity(set(routes[0].segment_ids), set(routes[1].segment_ids)) < 0.5


def test_loop_routes_return_best_effort_when_target_is_unreachable(db_connection) -> None:
    _build_loop_graph(db_connection)
    refresh_graph(connection=db_connection)

    routes = suggest_loop_routes(
        Coordinate(lat=40.05001, lng=-74.05001),
        distance_m=2500.0,
        candidate_count=1,
    )

    assert len(routes) == 1
    assert routes[0].node_ids[0] == routes[0].node_ids[-1]
    assert len(routes[0].segment_ids) == len(set(routes[0].segment_ids))
    assert 800.0 <= routes[0].distance_m <= 1100.0
