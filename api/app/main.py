import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.ingest import (
    DEFAULT_BBOX,
    BoundingBox,
    OSMDataProvider,
    dispose_engine,
    get_engine,
    ingest_parks,
    ingest_pois,
    ingest_segments,
    ingest_water_features,
)
from app.routing import (
    Coordinate,
    RouteCandidate,
    suggest_loop_routes,
    suggest_point_to_point_routes,
)
from app.routing_graph import get_graph, refresh_graph
from app.score_batch import run_batch_scoring
from app.segments_display import (
    display_name_from_osm_tags,
    display_name_from_values,
)

logging.basicConfig(level=logging.INFO)

_AUTH_SCHEME = HTTPBearer(auto_error=False)
_ACTIVITY_SPEED_MPS = {
    "walk": 1.4,
    "run": 2.4,
}


class CoordinatePayload(BaseModel):
    lat: float
    lng: float


class RouteSuggestRequest(BaseModel):
    start: CoordinatePayload
    end: CoordinatePayload | None = None
    mode: Literal["loop", "point-to-point", "point-to-destination"]
    distance_m: float = Field(gt=0)
    activity: Literal["walk", "run"] = "walk"
    priority: Literal["highest-rated", "dining", "residential", "explore"] = "highest-rated"


class RouteSaveRequest(BaseModel):
    start: CoordinatePayload
    end: CoordinatePayload | None = None
    mode: Literal["loop", "point-to-point", "point-to-destination"]
    priority: Literal["highest-rated", "dining", "residential", "explore"]
    segment_ids: list[str] = Field(min_length=1)
    distance_m: float = Field(gt=0)
    duration_s: int = Field(gt=0)
    avg_score: float


def _coordinate_model_to_domain(value: CoordinatePayload) -> Coordinate:
    return Coordinate(lat=value.lat, lng=value.lng)


def _coordinate_to_geojson(value: Coordinate) -> list[float]:
    return [value.lng, value.lat]


def _duration_seconds(distance_m: float, activity: str) -> int:
    speed_mps = _ACTIVITY_SPEED_MPS[activity]
    return max(1, round(distance_m / speed_mps))


def _geometry_from_node_path(candidate: RouteCandidate) -> dict[str, Any]:
    graph = get_graph()
    coordinates: list[list[float]] = []
    for node_id in candidate.node_ids:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        coordinates.append(
            _coordinate_to_geojson(
                Coordinate(lat=float(node["lat"]), lng=float(node["lng"]))
            )
        )
    if len(coordinates) < 2:
        coordinates = [
            _coordinate_to_geojson(candidate.snapped_start),
            _coordinate_to_geojson(candidate.snapped_end),
        ]
    return {"type": "LineString", "coordinates": coordinates}


def _serialize_route_candidate(candidate: RouteCandidate, *, activity: str) -> dict[str, Any]:
    return {
        "segment_ids": candidate.segment_ids,
        "geometry": _geometry_from_node_path(candidate),
        "distance_m": candidate.distance_m,
        "duration_s": _duration_seconds(candidate.distance_m, activity),
        "avg_score": candidate.avg_score,
        "verified_count": candidate.verified_count,
        "unverified_count": candidate.unverified_count,
    }


def _require_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_AUTH_SCHEME),
) -> uuid.UUID:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization bearer token required",
        )

    try:
        user_id = uuid.UUID(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token must be a user UUID",
        ) from exc

    engine = get_engine()
    with engine.begin() as connection:
        user_exists = connection.execute(
            text("SELECT 1 FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        ).scalar()

    if user_exists is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found",
        )

    return user_id


def _suggest_routes(request: RouteSuggestRequest) -> list[RouteCandidate]:
    start = _coordinate_model_to_domain(request.start)

    if request.mode == "loop":
        routes = suggest_loop_routes(
            start,
            distance_m=request.distance_m,
            priority=request.priority,
        )
    else:
        if request.end is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="end is required for non-loop routes",
            )
        routes = suggest_point_to_point_routes(
            start,
            _coordinate_model_to_domain(request.end),
            priority=request.priority,
        )

    if not routes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No routes available for the requested parameters",
        )

    return routes


def _coordinates_from_segment_geometries(
    connection,
    segment_ids: list[str],
) -> list[list[float]]:
    if not segment_ids:
        return []

    rows = connection.execute(
        text(
            """
            SELECT id, ST_AsGeoJSON(geometry) AS geometry
            FROM segments
            WHERE id = ANY(:segment_ids)
            """
        ),
        {"segment_ids": segment_ids},
    ).mappings()

    geometries_by_id = {
        row["id"]: json.loads(row["geometry"])["coordinates"]
        for row in rows
        if row["geometry"]
    }

    coordinates: list[list[float]] = []
    for segment_id in segment_ids:
        segment_coordinates = geometries_by_id.get(segment_id)
        if not segment_coordinates:
            continue
        if not coordinates:
            coordinates.extend(segment_coordinates)
            continue
        if coordinates[-1] == segment_coordinates[0]:
            coordinates.extend(segment_coordinates[1:])
        else:
            coordinates.extend(segment_coordinates)
    return coordinates


def _segment_verification_counts(connection, segment_ids: list[str]) -> tuple[int, int]:
    if not segment_ids:
        return 0, 0

    rows = connection.execute(
        text(
            """
            SELECT id, verified
            FROM segments
            WHERE id = ANY(:segment_ids)
            """
        ),
        {"segment_ids": segment_ids},
    ).mappings()

    verified_by_id = {row["id"]: bool(row["verified"]) for row in rows}
    verified_count = sum(1 for segment_id in segment_ids if verified_by_id.get(segment_id))
    return verified_count, len(segment_ids) - verified_count


def _coordinate_from_row(lat: float | None, lng: float | None) -> dict[str, float] | None:
    if lat is None or lng is None:
        return None
    return {"lat": float(lat), "lng": float(lng)}


def _validate_route_save_request(connection, request: RouteSaveRequest) -> None:
    if request.mode != "loop" and request.end is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end is required for non-loop routes",
        )

    existing_segment_ids = set(
        connection.execute(
            text("SELECT id FROM segments WHERE id = ANY(:segment_ids)"),
            {"segment_ids": request.segment_ids},
        ).scalars()
    )
    missing_segment_ids = [segment_id for segment_id in request.segment_ids if segment_id not in existing_segment_ids]
    if missing_segment_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown segment ids: {', '.join(missing_segment_ids)}",
        )


def _cors_origins() -> list[str]:
    origins_env = os.environ.get("CORS_ORIGINS")
    if origins_env:
        return [origin.strip() for origin in origins_env.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Handle startup/shutdown events for the API."""
    refresh_graph()
    try:
        yield
    finally:
        dispose_engine()


app = FastAPI(title="Walkmap API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
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
            factors,
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
        "factors": row["factors"],
        "osm_tags": row["osm_tags"],
        "display_name": display_name_from_osm_tags(row["osm_tags"]),
    }


@app.post("/routes/suggest")
def suggest_routes(request: RouteSuggestRequest) -> dict[str, Any]:
    routes = _suggest_routes(request)
    return {"routes": [_serialize_route_candidate(route, activity=request.activity) for route in routes]}


@app.post("/routes")
def save_route(request: RouteSaveRequest, user_id: uuid.UUID = Depends(_require_user_id)) -> dict[str, Any]:
    engine = get_engine()
    with engine.begin() as connection:
        _validate_route_save_request(connection, request)
        row = connection.execute(
            text(
                """
                INSERT INTO routes (
                    user_id,
                    start_point,
                    end_point,
                    mode,
                    priority,
                    segment_ids,
                    distance_m,
                    duration_s,
                    avg_score
                )
                VALUES (
                    :user_id,
                    ST_SetSRID(ST_MakePoint(:start_lng, :start_lat), 4326),
                    CAST(
                        CASE
                            WHEN :end_lat IS NULL OR :end_lng IS NULL THEN NULL
                            ELSE ST_SetSRID(ST_MakePoint(:end_lng, :end_lat), 4326)
                        END AS geometry
                    ),
                    :mode,
                    :priority,
                    :segment_ids,
                    :distance_m,
                    :duration_s,
                    :avg_score
                )
                RETURNING id, created_at
                """
            ),
            {
                "user_id": user_id,
                "start_lat": request.start.lat,
                "start_lng": request.start.lng,
                "end_lat": request.end.lat if request.end else None,
                "end_lng": request.end.lng if request.end else None,
                "mode": request.mode,
                "priority": request.priority,
                "segment_ids": request.segment_ids,
                "distance_m": request.distance_m,
                "duration_s": request.duration_s,
                "avg_score": request.avg_score,
            },
        ).mappings().one()

        verified_count, unverified_count = _segment_verification_counts(connection, request.segment_ids)
        coordinates = _coordinates_from_segment_geometries(connection, request.segment_ids)

    return {
        "route_id": str(row["id"]),
        "user_id": str(user_id),
        "start": request.start.model_dump(),
        "end": request.end.model_dump() if request.end else None,
        "mode": request.mode,
        "priority": request.priority,
        "segment_ids": request.segment_ids,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "distance_m": request.distance_m,
        "duration_s": request.duration_s,
        "avg_score": request.avg_score,
        "verified_count": verified_count,
        "unverified_count": unverified_count,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@app.get("/users/me/routes")
def get_my_routes(user_id: uuid.UUID = Depends(_require_user_id)) -> dict[str, Any]:
    engine = get_engine()
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    id,
                    mode,
                    priority,
                    segment_ids,
                    distance_m,
                    duration_s,
                    avg_score,
                    ST_Y(start_point) AS start_lat,
                    ST_X(start_point) AS start_lng,
                    ST_Y(end_point) AS end_lat,
                    ST_X(end_point) AS end_lng,
                    created_at
                FROM routes
                WHERE user_id = :user_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"user_id": user_id},
        ).mappings().all()

        history = []
        for row in rows:
            segment_ids = list(row["segment_ids"] or [])
            verified_count, unverified_count = _segment_verification_counts(connection, segment_ids)
            coordinates = _coordinates_from_segment_geometries(connection, segment_ids)
            history.append(
                {
                    "route_id": str(row["id"]),
                    "start": _coordinate_from_row(row["start_lat"], row["start_lng"]),
                    "end": _coordinate_from_row(row["end_lat"], row["end_lng"]),
                    "mode": row["mode"],
                    "priority": row["priority"],
                    "segment_ids": segment_ids,
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "distance_m": row["distance_m"],
                    "duration_s": row["duration_s"],
                    "avg_score": row["avg_score"],
                    "verified_count": verified_count,
                    "unverified_count": unverified_count,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )

    return {"routes": history}
