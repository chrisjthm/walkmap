from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from geoalchemy2.shape import from_shape
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from app.db.models import Park, Segment, WaterFeature

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


@dataclass(frozen=True)
class ParkRecord:
    """Park polygon payload derived from OSM features."""
    park_id: str
    name: str | None
    geometry: Any
    osm_tags: dict[str, Any]


@dataclass(frozen=True)
class WaterRecord:
    """Water feature payload derived from OSM features."""
    water_id: str
    name: str | None
    geometry: Any
    osm_tags: dict[str, Any]


@dataclass(frozen=True)
class SidewalkCandidate:
    geometry: Any
    geom_line: Any
    azimuth: float | None
    sidewalk_of: str | None
    name: str | None


class DataProvider(Protocol):
    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        """Return segment records for a bounding box."""
        ...

    def fetch_parks(self, bbox: BoundingBox) -> list[ParkRecord]:
        """Return park records for a bounding box."""
        ...

    def fetch_water_features(self, bbox: BoundingBox) -> list[WaterRecord]:
        """Return water feature records for a bounding box."""
        ...


class OSMDataProvider:
    def fetch_segments(self, bbox: BoundingBox) -> list[SegmentRecord]:
        """Fetch walkable OSM segments within a bounding box."""
        import osmnx as ox
        from shapely.geometry import box
        from shapely.ops import linemerge

        graph = ox.graph_from_bbox(
            bbox.north,
            bbox.south,
            bbox.east,
            bbox.west,
            network_type="walk",
        )
        edges = ox.graph_to_gdfs(graph, nodes=False, edges=True)
        bbox_polygon = box(bbox.west, bbox.south, bbox.east, bbox.north)
        center_lat = (bbox.south + bbox.north) / 2.0
        near_deg = _meters_to_degrees(20.0, center_lat)

        sidewalk_candidates: list[SidewalkCandidate] = []
        candidates: list[tuple[str, Any, dict[str, Any], Any, float | None, str | None]] = []
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
            geom_line = _line_for_azimuth(geometry, linemerge)
            azimuth = _azimuth_for_line(geom_line)
            name = osm_tags.get("name")
            if _is_sidewalk_candidate(osm_tags):
                sidewalk_candidates.append(
                    SidewalkCandidate(
                        geometry=geometry,
                        geom_line=geom_line or geometry,
                        azimuth=azimuth,
                        sidewalk_of=osm_tags.get("sidewalk:of"),
                        name=name,
                    )
                )
            candidates.append((segment_id, geometry, osm_tags, geom_line, azimuth, name))

        for segment_id, geometry, osm_tags, geom_line, azimuth, name in candidates:
            highway = _normalize_highway_value(osm_tags.get("highway"))
            if highway is None:
                continue
            if highway in _ALWAYS_EXCLUDE_HIGHWAYS:
                continue
            if highway in _PEDESTRIAN_HIGHWAYS or highway == "living_street":
                segments.append(
                    SegmentRecord(
                        segment_id=segment_id,
                        geometry=geometry,
                        osm_tags=osm_tags,
                    )
                )
                continue

            if highway == "secondary":
                if _has_sidewalk_tag(osm_tags, strict=True):
                    segments.append(
                        SegmentRecord(
                            segment_id=segment_id,
                            geometry=geometry,
                            osm_tags=osm_tags,
                        )
                    )
                continue

            if highway == "tertiary":
                if _has_sidewalk_tag(osm_tags):
                    segments.append(
                        SegmentRecord(
                            segment_id=segment_id,
                            geometry=geometry,
                            osm_tags=osm_tags,
                        )
                    )
                continue

            if highway == "residential":
                has_sidewalk_tag = _has_sidewalk_tag(osm_tags)
                has_parallel_sidewalk = False
                if not has_sidewalk_tag:
                    has_parallel_sidewalk = _has_parallel_sidewalk(
                        geom_line or geometry,
                        azimuth,
                        name,
                        sidewalk_candidates,
                        near_deg,
                    )
                if has_parallel_sidewalk:
                    continue
                if not has_sidewalk_tag:
                    osm_tags = dict(osm_tags)
                    osm_tags["walkmap_score_adjustment"] = -15.0
                segments.append(
                    SegmentRecord(
                        segment_id=segment_id,
                        geometry=geometry,
                        osm_tags=osm_tags,
                    )
                )
                continue

        return segments

    def fetch_parks(self, bbox: BoundingBox) -> list[ParkRecord]:
        """Fetch park and greenspace polygons within a bounding box."""
        import osmnx as ox
        tags = {
            "leisure": ["park", "playground", "dog_park", "garden"],
            "landuse": ["grass", "recreation_ground"],
        }
        gdf = ox.features_from_bbox(
            bbox.north,
            bbox.south,
            bbox.east,
            bbox.west,
            tags=tags,
        )
        if gdf.empty:
            return []
        if gdf.crs is not None and gdf.crs.to_epsg() not in (4326, None):
            gdf = gdf.to_crs(epsg=4326)
        parks: list[ParkRecord] = []
        for _, row in gdf.iterrows():
            geometry = row.get("geometry")
            if geometry is None:
                continue
            if geometry.is_empty:
                continue
            osm_tags = normalize_osm_tags(row.to_dict())
            osm_tags.pop("geometry", None)
            osmid = osm_tags.get("osmid", row.get("osmid"))
            element_type = row.get("element_type")
            if osmid is None:
                index_value = row.name
                if isinstance(index_value, tuple) and index_value:
                    osmid = index_value[0]
                    if element_type is None and len(index_value) > 1:
                        element_type = index_value[1]
                else:
                    osmid = index_value
            if element_type is None:
                element_type = osm_tags.get("element_type")
            if osmid is None:
                continue
            park_id = normalize_osmid(osmid)
            if element_type:
                park_id = f"{element_type}-{park_id}"
            parks.append(
                ParkRecord(
                    park_id=park_id,
                    name=osm_tags.get("name"),
                    geometry=geometry,
                    osm_tags=osm_tags,
                )
            )
        return parks

    def fetch_water_features(self, bbox: BoundingBox) -> list[WaterRecord]:
        """Fetch water features within a bounding box."""
        import osmnx as ox

        tags = {
            "natural": ["water"],
            "waterway": True,
            "leisure": ["marina"],
        }
        gdf = ox.features_from_bbox(
            bbox.north,
            bbox.south,
            bbox.east,
            bbox.west,
            tags=tags,
        )
        if gdf.empty:
            return []
        if gdf.crs is not None and gdf.crs.to_epsg() not in (4326, None):
            gdf = gdf.to_crs(epsg=4326)
        features: list[WaterRecord] = []
        for _, row in gdf.iterrows():
            geometry = row.get("geometry")
            if geometry is None:
                continue
            if geometry.is_empty:
                continue
            osm_tags = normalize_osm_tags(row.to_dict())
            osm_tags.pop("geometry", None)
            osmid = osm_tags.get("osmid", row.get("osmid"))
            element_type = row.get("element_type")
            if osmid is None:
                index_value = row.name
                if isinstance(index_value, tuple) and index_value:
                    osmid = index_value[0]
                    if element_type is None and len(index_value) > 1:
                        element_type = index_value[1]
                else:
                    osmid = index_value
            if element_type is None:
                element_type = osm_tags.get("element_type")
            if osmid is None:
                continue
            water_id = normalize_osmid(osmid)
            if element_type:
                water_id = f"{element_type}-{water_id}"
            features.append(
                WaterRecord(
                    water_id=water_id,
                    name=osm_tags.get("name"),
                    geometry=geometry,
                    osm_tags=osm_tags,
                )
            )
        return features


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


_PEDESTRIAN_HIGHWAYS = {"footway", "path", "pedestrian", "steps"}
_ALWAYS_EXCLUDE_HIGHWAYS = {"motorway", "trunk", "primary", "service", "track"}
_SIDEWALK_TAGS = {"both", "left", "right", "yes"}
_SIDEWALK_TAGS_STRICT = {"both", "left", "right"}


def _tag_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _tag_in(value: Any, options: set[str]) -> bool:
    return any(tag in options for tag in _tag_values(value))


def _normalize_highway_value(highway: Any) -> str | None:
    if highway is None:
        return None
    if isinstance(highway, (list, tuple, set)):
        candidates = [str(item).strip() for item in highway if str(item).strip()]
        if not candidates:
            return None
        priority = [
            "footway",
            "path",
            "pedestrian",
            "steps",
            "living_street",
            "residential",
            "tertiary",
            "secondary",
            "service",
            "track",
            "primary",
            "trunk",
            "motorway",
        ]
        for preferred in priority:
            if preferred in candidates:
                return preferred
        return candidates[0]
    value = str(highway).strip()
    return value or None


def _has_sidewalk_tag(osm_tags: dict[str, Any], strict: bool = False) -> bool:
    sidewalk = osm_tags.get("sidewalk")
    options = _SIDEWALK_TAGS_STRICT if strict else _SIDEWALK_TAGS
    return _tag_in(sidewalk, options)


def _is_sidewalk_candidate(osm_tags: dict[str, Any]) -> bool:
    footway = osm_tags.get("footway")
    highway = _normalize_highway_value(osm_tags.get("highway"))
    name = osm_tags.get("name")
    sidewalk_of = osm_tags.get("sidewalk:of")
    if sidewalk_of:
        return True
    if _tag_in(footway, {"sidewalk"}):
        return True
    if highway == "footway" and not name:
        if footway is None:
            return True
        return _tag_in(footway, {"sidewalk", "both", "left", "right"})
    return False


def _line_for_azimuth(geometry: Any, linemerge) -> Any:
    if geometry is None:
        return None
    if getattr(geometry, "is_empty", False):
        return None
    if getattr(geometry, "geom_type", "") == "LineString":
        return geometry
    line = linemerge(geometry)
    if getattr(line, "geom_type", "") == "LineString":
        return line
    if getattr(line, "geom_type", "") == "MultiLineString":
        try:
            return max(line.geoms, key=lambda item: item.length)
        except ValueError:
            return None
    return None


def _azimuth_for_line(line: Any) -> float | None:
    if line is None:
        return None
    coords = getattr(line, "coords", None)
    if coords is None:
        return None
    coords_list = list(coords)
    if len(coords_list) < 2:
        return None
    start = coords_list[0]
    end = coords_list[-1]
    return math.atan2(end[0] - start[0], end[1] - start[1])


def _azimuth_parallel(a: float, b: float) -> bool:
    diff = abs(a - b)
    diff = min(diff, 2 * math.pi - diff)
    diff_deg = math.degrees(diff)
    return diff_deg <= 20 or diff_deg >= 160


def _meters_to_degrees(meters: float, latitude: float) -> float:
    meters_per_degree_lon = 111_320 * abs(math.cos(math.radians(latitude)))
    meters_per_degree = min(111_320, meters_per_degree_lon or 111_320)
    return meters / meters_per_degree


def _has_parallel_sidewalk(
    geom_line: Any,
    azimuth: float | None,
    name: str | None,
    sidewalks: list[SidewalkCandidate],
    near_deg: float,
) -> bool:
    if geom_line is None:
        return False
    for sidewalk in sidewalks:
        if sidewalk.geom_line is None:
            continue
        if sidewalk.geom_line.distance(geom_line) > near_deg:
            continue
        if name and sidewalk.sidewalk_of and sidewalk.sidewalk_of == name:
            return True
        if azimuth is not None and sidewalk.azimuth is not None:
            if _azimuth_parallel(azimuth, sidewalk.azimuth):
                return True
    return False


def get_engine() -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL with a short connect timeout."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(database_url, connect_args={"connect_timeout": 5})


def ingest_segments(
    bbox: BoundingBox,
    provider: DataProvider,
    chunk_size: int = 500,
    engine: Engine | None = None,
    connection: Connection | None = None,
) -> int:
    """Upsert segments into the database and return the written row count."""
    segments = provider.fetch_segments(bbox)
    if not segments:
        return 0

    if connection is None:
        engine = engine or get_engine()
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
    update_fields = {
        "geometry": "geometry",
        "osm_tags": "osm_tags",
        "last_updated": "last_updated",
    }
    if connection is None:
        with engine.begin() as connection:
            total_written = _write_batches(connection, table, rows, chunk_size, update_fields)
    else:
        total_written = _write_batches(connection, table, rows, chunk_size, update_fields)

    return total_written


def ingest_parks(
    bbox: BoundingBox,
    provider: DataProvider,
    chunk_size: int = 200,
    engine: Engine | None = None,
    connection: Connection | None = None,
) -> int:
    """Upsert parks into the database and return the written row count."""
    parks = provider.fetch_parks(bbox)
    if not parks:
        return 0

    if connection is None:
        engine = engine or get_engine()
    table = Park.__table__

    rows_by_id: dict[str, dict[str, Any]] = {}
    for park in parks:
        rows_by_id[park.park_id] = {
            "id": park.park_id,
            "name": park.name,
            "geometry": from_shape(park.geometry, srid=4326),
            "osm_tags": park.osm_tags,
        }
    rows = list(rows_by_id.values())

    total_written = 0
    update_fields = {
        "geometry": "geometry",
        "osm_tags": "osm_tags",
        "name": "name",
    }
    if connection is None:
        with engine.begin() as connection:
            total_written = _write_batches(connection, table, rows, chunk_size, update_fields)
    else:
        total_written = _write_batches(connection, table, rows, chunk_size, update_fields)

    return total_written


def ingest_water_features(
    bbox: BoundingBox,
    provider: DataProvider,
    chunk_size: int = 200,
    engine: Engine | None = None,
    connection: Connection | None = None,
) -> int:
    """Upsert water features into the database and return the written row count."""
    features = provider.fetch_water_features(bbox)
    if not features:
        return 0

    if connection is None:
        engine = engine or get_engine()
    table = WaterFeature.__table__

    rows_by_id: dict[str, dict[str, Any]] = {}
    for feature in features:
        rows_by_id[feature.water_id] = {
            "id": feature.water_id,
            "name": feature.name,
            "geometry": from_shape(feature.geometry, srid=4326),
            "osm_tags": feature.osm_tags,
        }
    rows = list(rows_by_id.values())

    total_written = 0
    update_fields = {
        "geometry": "geometry",
        "osm_tags": "osm_tags",
        "name": "name",
    }
    if connection is None:
        with engine.begin() as connection:
            total_written = _write_batches(connection, table, rows, chunk_size, update_fields)
    else:
        total_written = _write_batches(connection, table, rows, chunk_size, update_fields)

    return total_written


def _write_batches(
    connection: Connection,
    table,
    rows: list[dict[str, Any]],
    chunk_size: int,
    update_fields: dict[str, str],
) -> int:
    total_written = 0
    for batch in chunked(rows, chunk_size):
        stmt = insert(table).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.id],
            set_={column: getattr(stmt.excluded, source) for column, source in update_fields.items()},
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
    segment_count = ingest_segments(bbox, provider)
    park_count = ingest_parks(bbox, provider)
    water_count = ingest_water_features(bbox, provider)
    print(
        f"Ingested {segment_count} segments, {park_count} parks, and {water_count} water features"
    )


if __name__ == "__main__":
    main()
