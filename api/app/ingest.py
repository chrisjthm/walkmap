from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from geoalchemy2.shape import from_shape
from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from app.db.models import Segment


DEFAULT_BBOX = {
    "north": 40.7282,
    "south": 40.7080,
    "east": -74.0150,
    "west": -74.0600,
}


@dataclass(frozen=True)
class BoundingBox:
    """Bounding box limits for OSM queries."""
    north: float
    south: float
    east: float
    west: float


@dataclass(frozen=True)
class SegmentRecord:
    """Segment payload derived from OSM edges."""
    segment_id: str
    geometry: Any
    osm_tags: dict[str, Any]


class DataProvider(Protocol):
    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        """Return segment records for a bounding box."""
        ...


class OSMDataProvider:
    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        """Fetch walkable OSM segments within a bounding box."""
        import osmnx as ox
        from shapely.geometry import box

        graph = ox.graph_from_bbox(
            bbox.north,
            bbox.south,
            bbox.east,
            bbox.west,
            network_type="walk",
        )
        edges = ox.graph_to_gdfs(graph, nodes=False, edges=True)
        bbox_polygon = box(bbox.west, bbox.south, bbox.east, bbox.north)

        segments: list[SegmentRecord] = []
        for (u, v, key), row in edges.iterrows():
            osmid = row.get("osmid")
            segment_id = build_segment_id(osmid, u, v, key)
            geometry = row.get("geometry")
            if geometry is None:
                continue
            if not geometry.within(bbox_polygon):
                continue

            osm_tags = normalize_osm_tags(row.to_dict())
            osm_tags.pop("geometry", None)
            segments.append(
                SegmentRecord(
                    segment_id=segment_id,
                    geometry=geometry,
                    osm_tags=osm_tags,
                )
            )

        return segments


def build_segment_id(osmid: Any, u: Any, v: Any, key: Any) -> str:
    """Build a stable string identifier for a graph edge."""
    osmid_part = normalize_osmid(osmid)
    return f"{osmid_part}:{u}:{v}:{key}"


def normalize_osmid(osmid: Any) -> str:
    """Normalize OSM IDs into a string, joining lists when needed."""
    if isinstance(osmid, (list, tuple, set)):
        return "-".join(str(item) for item in osmid)
    return str(osmid)


def normalize_osm_tags(tags: dict[str, Any]) -> dict[str, Any]:
    """Filter out null/NaN values and normalize types for JSON storage."""
    normalized: dict[str, Any] = {}
    for key, value in tags.items():
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        normalized[key] = normalize_value(value)
    return normalized


def normalize_value(value: Any) -> Any:
    """Coerce tag values into JSON-serializable types."""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [normalize_value(item) for item in value]
    try:
        return value.item()
    except AttributeError:
        return str(value)


def get_engine() -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(database_url)


def ingest_segments(bbox: BoundingBox, provider: DataProvider, chunk_size: int = 500) -> int:
    """Upsert segments into the database and return the written row count."""
    segments = provider.fetch_segments(bbox)
    if not segments:
        return 0

    engine = get_engine()
    table = Segment.__table__

    rows: list[dict[str, Any]] = []
    for segment in segments:
        rows.append(
            {
                "id": segment.segment_id,
                "geometry": from_shape(segment.geometry, srid=4326),
                "osm_tags": segment.osm_tags,
                "ai_score": None,
                "ai_confidence": None,
                "user_score": None,
                "composite_score": None,
                "last_updated": func.now(),
            }
        )

    total_written = 0
    with engine.begin() as connection:
        for batch in chunked(rows, chunk_size):
            stmt = insert(table).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=[table.c.id],
                set_={
                    "geometry": stmt.excluded.geometry,
                    "osm_tags": stmt.excluded.osm_tags,
                    "last_updated": stmt.excluded.last_updated,
                },
            )
            result = connection.execute(stmt)
            total_written += result.rowcount or 0

    return total_written


def chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    """Yield rows in fixed-size batches."""
    for idx in range(0, len(rows), size):
        yield rows[idx : idx + size]


def parse_args() -> BoundingBox:
    """Parse CLI arguments into a bounding box."""
    parser = argparse.ArgumentParser(description="Ingest OSM segments into the database")
    parser.add_argument("--north", type=float, default=DEFAULT_BBOX["north"])
    parser.add_argument("--south", type=float, default=DEFAULT_BBOX["south"])
    parser.add_argument("--east", type=float, default=DEFAULT_BBOX["east"])
    parser.add_argument("--west", type=float, default=DEFAULT_BBOX["west"])
    args = parser.parse_args()
    return BoundingBox(north=args.north, south=args.south, east=args.east, west=args.west)


def main() -> None:
    """CLI entrypoint for OSM ingestion."""
    bbox = parse_args()
    provider = OSMDataProvider()
    count = ingest_segments(bbox, provider)
    print(f"Ingested {count} segments")


if __name__ == "__main__":
    main()
