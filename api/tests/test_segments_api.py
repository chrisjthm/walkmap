from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


def _insert_segment(
    db_connection,
    segment_id: str,
    wkt: str,
    composite_score: float = 72.0,
    verified: bool = True,
    rating_count: int = 3,
    vibe_tag_counts: dict[str, int] | None = None,
    ai_score: float | None = None,
    ai_confidence: float | None = None,
    osm_tags: dict | None = None,
) -> None:
    vibe_tag_counts = vibe_tag_counts or {"scenic": 2}
    osm_tags = osm_tags or {"highway": "residential"}
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
                :rating_count,
                CAST(:vibe_tag_counts AS jsonb)
            )
            """
        ),
        {
            "id": segment_id,
            "wkt": wkt,
            "osm_tags": json.dumps(osm_tags),
            "ai_score": ai_score,
            "ai_confidence": ai_confidence,
            "composite_score": composite_score,
            "verified": verified,
            "rating_count": rating_count,
            "vibe_tag_counts": json.dumps(vibe_tag_counts),
        },
    )


def _client() -> TestClient:
    return TestClient(app)


def test_segments_bbox_returns_expected_segment(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-waterfront",
        "LINESTRING(-74.0400 40.7160, -74.0380 40.7175)",
        composite_score=88,
    )
    _insert_segment(
        db_connection,
        "seg-outside",
        "LINESTRING(-75.0000 41.0000, -75.0010 41.0010)",
        composite_score=20,
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.05,40.71,-74.03,40.72")

    assert response.status_code == 200
    payload = response.json()
    features_by_id = {feature["properties"]["segment_id"]: feature for feature in payload["features"]}
    assert "seg-waterfront" in features_by_id
    assert "seg-outside" not in features_by_id
    props = features_by_id["seg-waterfront"]["properties"]
    assert "composite_score" in props
    assert "verified" in props
    assert "rating_count" in props
    assert "vibe_tag_counts" in props
    assert "display_name" in props


def test_segments_bbox_empty_returns_empty_collection(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-waterfront",
        "LINESTRING(-74.0400 40.7160, -74.0380 40.7175)",
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-73.9,40.9,-73.8,41.0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert payload["features"] == []


def test_segments_bbox_features_within_bounds(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-center",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
    )
    db_connection.commit()

    west, south, east, north = -74.05, 40.71, -74.03, 40.72
    client = _client()
    response = client.get(f"/segments?bbox={west},{south},{east},{north}")

    assert response.status_code == 200
    payload = response.json()
    for feature in payload["features"]:
        assert feature["geometry"]["type"] == "LineString"
        for lon, lat in feature["geometry"]["coordinates"]:
            assert west <= lon <= east
            assert south <= lat <= north


def test_segment_detail_endpoint_returns_full_detail(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-detail",
        "LINESTRING(-74.0400 40.7160, -74.0380 40.7175)",
        composite_score=66,
        verified=False,
        rating_count=1,
        ai_score=61,
        ai_confidence=0.42,
        osm_tags={"highway": "footway"},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments/seg-detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["segment_id"] == "seg-detail"
    assert payload["ai_score"] == 61
    assert payload["ai_confidence"] == 0.42
    assert payload["osm_tags"]["highway"] == "footway"
    assert payload["display_name"] == "Footway"
    assert "geometry" in payload
    assert payload["geometry"]["type"] == "LineString"


def test_segment_detail_endpoint_404(db_connection) -> None:
    client = _client()
    response = client.get("/segments/does-not-exist")

    assert response.status_code == 404


def test_segments_response_is_valid_geojson(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-geojson",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.05,40.71,-74.03,40.72")

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert isinstance(payload["features"], list)
    feature = payload["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "LineString"
    assert isinstance(feature["geometry"]["coordinates"], list)


def test_segments_bbox_display_name_prefers_osm_name(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-named",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
        osm_tags={"name": "Grove Street", "highway": "residential"},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.05,40.71,-74.03,40.72")

    assert response.status_code == 200
    payload = response.json()
    feature = payload["features"][0]
    assert feature["properties"]["display_name"] == "Grove Street"


def test_segments_bbox_display_name_falls_back_to_highway(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-footway",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
        osm_tags={"highway": "footway"},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.05,40.71,-74.03,40.72")

    assert response.status_code == 200
    payload = response.json()
    feature = payload["features"][0]
    assert feature["properties"]["display_name"] == "Footway"


def test_segments_bbox_display_name_handles_multiple_highway_tags(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-multi-highway",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
        osm_tags={"highway": ["path", "footway"]},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.05,40.71,-74.03,40.72")

    assert response.status_code == 200
    payload = response.json()
    feature = payload["features"][0]
    assert feature["properties"]["display_name"] == "Footway"


def test_segments_bbox_suppresses_sidewalks_when_carriageway_present(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-morris",
        "LINESTRING(-74.0400 40.7160, -74.0400 40.7170)",
        osm_tags={"highway": "residential", "name": "Morris Street"},
    )
    _insert_segment(
        db_connection,
        "seg-morris-sidewalk-west",
        "LINESTRING(-74.0402 40.7160, -74.0402 40.7170)",
        osm_tags={"highway": "footway", "sidewalk:of": "Morris Street"},
    )
    _insert_segment(
        db_connection,
        "seg-morris-sidewalk-east",
        "LINESTRING(-74.0398 40.7160, -74.0398 40.7170)",
        osm_tags={"highway": "footway", "sidewalk:of": "Morris Street"},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.0403,40.7159,-74.0397,40.7171")

    assert response.status_code == 200
    payload = response.json()
    feature_ids = {feature["properties"]["segment_id"] for feature in payload["features"]}
    assert "seg-morris" in feature_ids
    assert "seg-morris-sidewalk-west" not in feature_ids
    assert "seg-morris-sidewalk-east" not in feature_ids


def test_segments_bbox_sidewalk_inherits_name_when_parent_outside_bbox(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-morris-parent",
        "LINESTRING(-74.0402 40.7160, -74.0402 40.7170)",
        osm_tags={"highway": "residential", "name": "Morris Street"},
    )
    _insert_segment(
        db_connection,
        "seg-morris-sidewalk",
        "LINESTRING(-74.0400 40.7160, -74.0400 40.7170)",
        osm_tags={"highway": "footway", "footway": "sidewalk"},
    )
    db_connection.commit()

    client = _client()
    response = client.get("/segments?bbox=-74.04005,40.7159,-74.03995,40.7171")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["properties"]["segment_id"] == "seg-morris-sidewalk"
    assert feature["properties"]["display_name"] == "Morris Street"


def test_segments_bbox_query_uses_gist_index(db_connection) -> None:
    _insert_segment(
        db_connection,
        "seg-index",
        "LINESTRING(-74.0410 40.7155, -74.0390 40.7165)",
    )
    db_connection.execute(text("SET enable_seqscan = off"))

    explain = db_connection.execute(
        text(
            """
            EXPLAIN ANALYZE
            SELECT id
            FROM segments
            WHERE ST_Intersects(
                geometry,
                ST_MakeEnvelope(:west, :south, :east, :north, 4326)
            )
            """
        ),
        {"west": -74.05, "south": 40.71, "east": -74.03, "north": 40.72},
    ).fetchall()
    plan_text = "\n".join(row[0] for row in explain)

    assert "ix_segments_geometry" in plan_text
    match = re.search(r"Execution Time: ([0-9.]+) ms", plan_text)
    assert match is not None
    assert float(match.group(1)) < 500.0
