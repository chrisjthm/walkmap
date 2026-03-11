from __future__ import annotations

from shapely.geometry import LineString
from sqlalchemy import text

from app.ingest import (
    BoundingBox,
    SegmentRecord,
    build_segment_id,
    ingest_segments,
    normalize_osm_tags,
)


class FakeProvider:
    def __init__(self, records: list[SegmentRecord]) -> None:
        self._records = records

    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        return self._records


def test_build_segment_id_handles_multi_osmid() -> None:
    segment_id = build_segment_id([123, 456], 1, 2, 0)
    assert segment_id == "123-456:1:2:0"


def test_normalize_osm_tags_filters_nulls() -> None:
    tags = {"highway": "residential", "foo": None, "bar": float("nan")}
    normalized = normalize_osm_tags(tags)
    assert normalized == {"highway": "residential"}


def test_ingest_segments_inserts_and_is_idempotent(db_connection) -> None:
    bbox = BoundingBox(north=40.0, south=39.0, east=-73.0, west=-74.0)
    records = [
        SegmentRecord(
            segment_id="seg-1",
            geometry=LineString([(-74.0, 40.0), (-74.001, 40.001)]),
            osm_tags={"highway": "residential"},
        ),
        SegmentRecord(
            segment_id="seg-2",
            geometry=LineString([(-74.0, 40.0), (-74.002, 40.002)]),
            osm_tags={"highway": "footway"},
        ),
    ]
    provider = FakeProvider(records)

    count_first = ingest_segments(bbox, provider, connection=db_connection)
    count_second = ingest_segments(bbox, provider, connection=db_connection)

    total = db_connection.execute(text("SELECT COUNT(*) FROM segments")).scalar_one()
    assert total == 2
    assert count_second <= count_first


def test_ingest_segments_geometry_and_ai_fields(db_connection) -> None:
    bbox = BoundingBox(north=40.0, south=39.0, east=-73.0, west=-74.0)
    records = [
        SegmentRecord(
            segment_id="seg-3",
            geometry=LineString([(-74.0, 40.0), (-74.003, 40.003)]),
            osm_tags={"highway": "residential"},
        )
    ]
    provider = FakeProvider(records)
    ingest_segments(bbox, provider, connection=db_connection)

    wkt = db_connection.execute(
        text("SELECT ST_AsText(geometry) FROM segments WHERE id = 'seg-3'")
    ).scalar_one()
    assert wkt.startswith("LINESTRING")

    is_valid = db_connection.execute(
        text("SELECT ST_IsValid(geometry) FROM segments WHERE id = 'seg-3'")
    ).scalar_one()
    assert is_valid is True

    ai_score = db_connection.execute(
        text("SELECT ai_score FROM segments WHERE id = 'seg-3'")
    ).scalar_one()
    assert ai_score is None

    osm_tags = db_connection.execute(
        text("SELECT osm_tags FROM segments WHERE id = 'seg-3'")
    ).scalar_one()
    assert osm_tags.get("highway") == "residential"
