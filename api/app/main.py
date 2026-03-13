import json
import os
from functools import lru_cache
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ingest import (
    DEFAULT_BBOX,
    BoundingBox,
    OSMDataProvider,
    get_engine,
    ingest_parks,
    ingest_pois,
    ingest_segments,
    ingest_water_features,
)
from app.score_batch import run_batch_scoring
from app.segments_display import (
    display_name_from_osm_tags,
    display_name_from_values,
)

app = FastAPI(title="Walkmap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be west,south,east,north")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox must be four numbers") from exc
    if west >= east or south >= north:
        raise HTTPException(status_code=400, detail="bbox coordinates are invalid")
    return west, south, east, north


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}

@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check for the API."""
    return {"status": "ok"}


@app.post("/admin/ingest/osm")
def ingest_osm(background_tasks: BackgroundTasks) -> dict[str, str | dict[str, float]]:
    """Queue a background ingest of OSM walkable segments for the MVP bbox.

    This endpoint is intended for manual/admin use to populate the `segments`
    table with OSM data (e.g., during initial setup or when refreshing data).
    It currently takes no request body; it always uses the configured MVP
    bounding box from `DEFAULT_BBOX`.
    """
    bbox = BoundingBox(**DEFAULT_BBOX)
    provider = OSMDataProvider()
    background_tasks.add_task(ingest_segments, bbox, provider)
    background_tasks.add_task(ingest_parks, bbox, provider)
    background_tasks.add_task(ingest_water_features, bbox, provider)
    background_tasks.add_task(ingest_pois, bbox, provider)
    return {"status": "queued", "bbox": DEFAULT_BBOX}


@app.post("/admin/score/batch")
def score_batch(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Queue a background scoring run for unscored segments.

    This endpoint is intended for manual/admin use to apply AI scores
    to any segments that still have ai_score = NULL.
    """
    background_tasks.add_task(run_batch_scoring)
    return {"status": "queued"}


CACHE_DECIMALS = 4


def _get_segments_impl(
    west: float, south: float, east: float, north: float
) -> dict[str, Any]:
    engine = get_engine()
    query = text(
        """
        SELECT
            id,
            composite_score,
            verified,
            rating_count,
            vibe_tag_counts,
            osm_tags,
            osm_tags->>'name' AS name,
            osm_tags->>'highway' AS highway,
            ST_AsGeoJSON(geometry) AS geometry
        FROM segments
        WHERE ST_Intersects(
            geometry,
            ST_MakeEnvelope(:west, :south, :east, :north, 4326)
        )
        """
    )
    with engine.begin() as connection:
        rows = connection.execute(
            query,
            {
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            },
        ).mappings()
        features = []
        for row in rows:
            geometry = json.loads(row["geometry"]) if row["geometry"] else None
            display_name = display_name_from_values(row["name"], row["highway"])
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "segment_id": row["id"],
                        "composite_score": row["composite_score"],
                        "verified": row["verified"],
                        "rating_count": row["rating_count"],
                        "vibe_tag_counts": row["vibe_tag_counts"],
                        "display_name": display_name,
                    },
                }
            )
    return _feature_collection(features)


_get_segments_cached = lru_cache(maxsize=256)(_get_segments_impl)


@app.get("/segments")
def get_segments(
    bbox: str = Query(..., description="west,south,east,north"),
) -> dict[str, Any]:
    """Return segments intersecting the bounding box as GeoJSON features."""
    west, south, east, north = _parse_bbox(bbox)
    west = round(west, CACHE_DECIMALS)
    south = round(south, CACHE_DECIMALS)
    east = round(east, CACHE_DECIMALS)
    north = round(north, CACHE_DECIMALS)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _get_segments_impl(west, south, east, north)
    return _get_segments_cached(west, south, east, north)


@app.get("/segments/{segment_id}")
def get_segment_detail(segment_id: str) -> dict[str, Any]:
    """Return full detail for a single segment."""
    engine = get_engine()
    query = text(
        """
        SELECT
            id,
            ai_score,
            ai_confidence,
            user_score,
            composite_score,
            verified,
            rating_count,
            vibe_tag_counts,
            osm_tags,
            ST_AsGeoJSON(geometry) AS geometry
        FROM segments
        WHERE id = :segment_id
        """
    )
    with engine.begin() as connection:
        row = (
            connection.execute(query, {"segment_id": segment_id}).mappings().first()
        )
    if row is None:
        raise HTTPException(status_code=404, detail="segment not found")
    geometry = json.loads(row["geometry"]) if row["geometry"] else None
    return {
        "segment_id": row["id"],
        "geometry": geometry,
        "ai_score": row["ai_score"],
        "ai_confidence": row["ai_confidence"],
        "user_score": row["user_score"],
        "composite_score": row["composite_score"],
        "verified": row["verified"],
        "rating_count": row["rating_count"],
        "vibe_tag_counts": row["vibe_tag_counts"],
        "osm_tags": row["osm_tags"],
        "display_name": display_name_from_osm_tags(row["osm_tags"]),
    }
