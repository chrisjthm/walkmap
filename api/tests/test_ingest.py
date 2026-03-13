from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from sqlalchemy import text

from app.ingest import (
    BoundingBox,
    ParkRecord,
    PoiRecord,
    SegmentRecord,
    _azimuth_parallel,
    _has_parallel_sidewalk,
    _has_sidewalk_tag,
    _is_sidewalk_candidate,
    _normalize_highway_value,
    build_segment_id,
    ingest_parks,
    ingest_pois,
    ingest_segments,
    normalize_osm_tags,
)


class FakeProvider:
    def __init__(self, records: list[SegmentRecord]) -> None:
        self._records = records

    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        return self._records

    def fetch_parks(self, bbox: BoundingBox) -> list[ParkRecord]:
        return []

    def fetch_water_features(self, bbox: BoundingBox) -> list:
        return []

    def fetch_pois(self, bbox: BoundingBox) -> list:
        return []


class FakeProviderWithParks(FakeProvider):
    def __init__(self, records: list[SegmentRecord], parks: list[ParkRecord]) -> None:
        super().__init__(records)
        self._parks = parks

    def fetch_parks(self, bbox: BoundingBox) -> list[ParkRecord]:
        return self._parks


class FakeProviderWithPois(FakeProvider):
    def __init__(self, records: list[SegmentRecord], pois: list[PoiRecord]) -> None:
        super().__init__(records)
        self._pois = pois

    def fetch_pois(self, bbox: BoundingBox) -> list[PoiRecord]:
        return self._pois


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


def test_ingest_parks_deduplicates_by_id(db_connection) -> None:
    bbox = BoundingBox(north=40.0, south=39.0, east=-73.0, west=-74.0)
    parks = [
        ParkRecord(
            park_id="way-100",
            name="Original Park",
            geometry=Polygon(
                [(-74.0, 40.0), (-74.0, 40.001), (-74.001, 40.001), (-74.001, 40.0)]
            ),
            osm_tags={"leisure": "park"},
        ),
        ParkRecord(
            park_id="way-100",
            name="Updated Park",
            geometry=Polygon(
                [(-74.0, 40.0), (-74.0, 40.002), (-74.002, 40.002), (-74.002, 40.0)]
            ),
            osm_tags={"leisure": "park", "name": "Updated Park"},
        ),
    ]
    provider = FakeProviderWithParks([], parks)

    ingest_parks(bbox, provider, connection=db_connection)

    total = db_connection.execute(text("SELECT COUNT(*) FROM parks")).scalar_one()
    assert total == 1
    name = db_connection.execute(
        text("SELECT name FROM parks WHERE id = 'way-100'")
    ).scalar_one()
    assert name == "Updated Park"


def test_ingest_pois_deduplicates_by_id(db_connection) -> None:
    bbox = BoundingBox(north=40.0, south=39.0, east=-73.0, west=-74.0)
    pois = [
        PoiRecord(
            poi_id="node-200",
            name="Original Cafe",
            geometry=Point(-74.0, 40.0),
            osm_tags={"amenity": "cafe"},
        ),
        PoiRecord(
            poi_id="node-200",
            name="Updated Cafe",
            geometry=Point(-74.0005, 40.0005),
            osm_tags={"amenity": "cafe", "name": "Updated Cafe"},
        ),
    ]
    provider = FakeProviderWithPois([], pois)

    ingest_pois(bbox, provider, connection=db_connection)

    total = db_connection.execute(text("SELECT COUNT(*) FROM pois")).scalar_one()
    assert total == 1
    name = db_connection.execute(
        text("SELECT name FROM pois WHERE id = 'node-200'")
    ).scalar_one()
    assert name == "Updated Cafe"


def test_normalize_highway_prefers_pedestrian_values() -> None:
    value = _normalize_highway_value(["path", "footway"])
    assert value == "footway"


def test_has_sidewalk_tag_accepts_yes_value() -> None:
    assert _has_sidewalk_tag({"sidewalk": "yes"}) is True


def test_is_sidewalk_candidate_footway_sidewalk() -> None:
    assert _is_sidewalk_candidate({"highway": "footway", "footway": "sidewalk"}) is True


def test_is_sidewalk_candidate_unnamed_footway() -> None:
    assert _is_sidewalk_candidate({"highway": "footway"}) is True


def test_is_sidewalk_candidate_named_footway_is_false() -> None:
    assert _is_sidewalk_candidate({"highway": "footway", "name": "Named Walk"}) is False


def test_is_sidewalk_candidate_sidewalk_of_tag() -> None:
    assert _is_sidewalk_candidate({"sidewalk:of": "Morris Street"}) is True


def test_parallel_sidewalk_detection() -> None:
    main_line = LineString([(-74.0, 40.0), (-74.0, 40.001)])
    sidewalk_line = LineString([(-74.0001, 40.0), (-74.0001, 40.001)])
    near_deg = 0.0003
    sidewalk = type("Sidewalk", (), {})()
    sidewalk.geom_line = sidewalk_line
    sidewalk.azimuth = 0.0
    sidewalk.sidewalk_of = "Morris Street"

    assert _has_parallel_sidewalk(
        geom_line=main_line,
        azimuth=0.0,
        name="Morris Street",
        sidewalks=[sidewalk],
        near_deg=near_deg,
    )


def test_parallel_sidewalk_rejects_perpendicular() -> None:
    main_line = LineString([(-74.0, 40.0), (-74.0, 40.001)])
    perpendicular = LineString([(-74.0, 40.0), (-74.001, 40.0)])
    near_deg = 0.0003
    sidewalk = type("Sidewalk", (), {})()
    sidewalk.geom_line = perpendicular
    sidewalk.azimuth = 1.57
    sidewalk.sidewalk_of = None

    assert not _has_parallel_sidewalk(
        geom_line=main_line,
        azimuth=0.0,
        name="Morris Street",
        sidewalks=[sidewalk],
        near_deg=near_deg,
    )


def test_azimuth_parallel_bounds() -> None:
    assert _azimuth_parallel(0.0, 0.1) is True
    assert _azimuth_parallel(0.0, 1.57) is False
