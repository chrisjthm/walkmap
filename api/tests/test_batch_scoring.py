from __future__ import annotations

from sqlalchemy import text

from app.score_batch import _fetch_nearby_pois, run_batch_scoring


def _insert_segment(db_connection, segment_id: str) -> None:
    db_connection.execute(
        text(
            """
            INSERT INTO segments (id, geometry, osm_tags, ai_score, ai_confidence, user_score, composite_score, verified, rating_count, vibe_tag_counts)
            VALUES (:id, ST_GeomFromText(:wkt, 4326), CAST(:osm_tags AS jsonb), NULL, NULL, NULL, NULL, FALSE, 0, '{}'::jsonb)
            """
        ),
        {
            "id": segment_id,
            "wkt": "LINESTRING(-74 40, -74.001 40.001)",
            "osm_tags": "{\"highway\":\"residential\"}",
        },
    )


def test_batch_scoring_updates_segments(db_connection) -> None:
    _insert_segment(db_connection, "seg-b3-1")
    _insert_segment(db_connection, "seg-b3-2")

    processed = run_batch_scoring(batch_size=1, connection=db_connection)
    assert processed == 2

    rows = db_connection.execute(
        text(
            """
            SELECT ai_score, ai_confidence, composite_score
            FROM segments
            WHERE id IN ('seg-b3-1', 'seg-b3-2')
            """
        )
    ).mappings().all()

    assert len(rows) == 2
    for row in rows:
        assert row["ai_score"] is not None
        assert 0.0 <= row["ai_confidence"] <= 1.0
        assert row["composite_score"] == row["ai_score"]

    processed_again = run_batch_scoring(batch_size=1, connection=db_connection)
    assert processed_again == 0


def test_fetch_nearby_pois_returns_osm_tags(db_connection) -> None:
    _insert_segment(db_connection, "seg-poi-1")
    db_connection.execute(
        text(
            """
            INSERT INTO pois (id, name, geometry, osm_tags)
            VALUES (:id, :name, ST_GeomFromText(:wkt, 4326), CAST(:osm_tags AS jsonb))
            """
        ),
        {
            "id": "poi-1",
            "name": "Test Cafe",
            "wkt": "POINT(-74.0005 40.0005)",
            "osm_tags": "{\"amenity\":\"cafe\"}",
        },
    )

    geometry_wkb = db_connection.execute(
        text("SELECT ST_AsEWKB(geometry) FROM segments WHERE id = :id"),
        {"id": "seg-poi-1"},
    ).scalar_one()

    pois = _fetch_nearby_pois(db_connection, geometry_wkb, 50)
    assert len(pois) == 1
    assert pois[0].get("amenity") == "cafe"
