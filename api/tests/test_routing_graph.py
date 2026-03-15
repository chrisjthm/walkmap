from __future__ import annotations

import json
import logging

from sqlalchemy import text

from app.routing_graph import refresh_graph


def _insert_segment(
    db_connection,
    segment_id: str,
    wkt: str,
    composite_score: float | None = 75.0,
    verified: bool = True,
    osm_tags: dict | None = None,
    ai_confidence: float | None = None,
) -> None:
    osm_tags = osm_tags or {"highway": "residential", "landuse": "residential"}
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
            "osm_tags": json.dumps(osm_tags),
            "ai_score": composite_score,
            "ai_confidence": ai_confidence,
            "composite_score": composite_score,
            "verified": verified,
        },
    )


def _insert_poi(db_connection, poi_id: str, wkt: str, osm_tags: dict | None = None) -> None:
    osm_tags = osm_tags or {"amenity": "restaurant"}
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
            "name": osm_tags.get("name"),
            "wkt": wkt,
            "osm_tags": json.dumps(osm_tags),
        },
    )


def test_refresh_graph_builds_and_sets_flags(db_connection) -> None:
    segment_with_poi = "1:100:200:0"
    segment_far = "2:300:400:0"

    _insert_segment(
        db_connection,
        segment_with_poi,
        "LINESTRING(-74.0000 40.0000, -74.0000 40.0005)",
        composite_score=80.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_segment(
        db_connection,
        segment_far,
        "LINESTRING(-74.0100 40.0100, -74.0110 40.0100)",
        composite_score=20.0,
        osm_tags={"highway": "footway"},
    )
    _insert_poi(db_connection, "poi-1", "POINT(-74.0000 40.00025)")

    cache = refresh_graph(connection=db_connection)

    assert cache.edge_count == 2
    assert cache.node_count >= 4

    edge_a = cache.graph["100"]["200"][segment_with_poi]
    edge_b = cache.graph["300"]["400"][segment_far]

    assert edge_a["segment_id"] == segment_with_poi
    assert edge_a["near_restaurant"] is True
    assert edge_a["is_residential"] is True
    assert edge_a["weight"] == 1.0 - (80.0 / 100.0)
    assert edge_a["distance_m"] > 0

    assert edge_b["near_restaurant"] is False
    assert edge_b["is_residential"] is False
    assert edge_b["weight"] == 1.0 - (20.0 / 100.0)


def test_refresh_graph_updates_weights_after_score_change(db_connection) -> None:
    segment_id = "9:500:600:0"
    _insert_segment(
        db_connection,
        segment_id,
        "LINESTRING(-74.0200 40.0200, -74.0205 40.0200)",
        composite_score=10.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )

    cache = refresh_graph(connection=db_connection)
    edge = cache.graph["500"]["600"][segment_id]
    assert edge["weight"] == 1.0 - (10.0 / 100.0)

    db_connection.execute(
        text("UPDATE segments SET composite_score = 90 WHERE id = :id"),
        {"id": segment_id},
    )

    cache = refresh_graph(connection=db_connection)
    edge = cache.graph["500"]["600"][segment_id]
    assert edge["weight"] == 1.0 - (90.0 / 100.0)


def test_refresh_graph_logs_disconnected_components(db_connection, caplog) -> None:
    _insert_segment(
        db_connection,
        "3:700:800:0",
        "LINESTRING(-74.0300 40.0300, -74.0305 40.0300)",
        composite_score=70.0,
        osm_tags={"highway": "residential", "landuse": "residential"},
    )
    _insert_segment(
        db_connection,
        "4:900:1000:0",
        "LINESTRING(-74.0400 40.0400, -74.0405 40.0400)",
        composite_score=60.0,
        osm_tags={"highway": "footway"},
    )

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.routing_graph"):
        cache = refresh_graph(connection=db_connection)

    assert cache.component_count >= 2
    assert any("disconnected components" in record.getMessage() for record in caplog.records)
