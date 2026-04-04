from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.routing_graph import refresh_graph


def _client() -> TestClient:
    return TestClient(app)


def _insert_segment(
    db_connection,
    segment_id: str,
    wkt: str,
    *,
    composite_score: float,
    verified: bool = True,
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
            "ai_confidence": 0.9,
            "composite_score": composite_score,
            "verified": verified,
        },
    )


def _insert_user(db_connection, user_id: uuid.UUID) -> None:
    password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode("utf-8")
    db_connection.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash)
            VALUES (:id, :email, :password_hash)
            """
        ),
        {
            "id": user_id,
            "email": f"{user_id}@example.com",
            "password_hash": password_hash,
        },
    )


def _build_loop_graph(db_connection) -> None:
    segments = [
        ("40:1:2:0", "LINESTRING(-74.0500 40.0500, -74.0500 40.0530)", 92.0, True),
        ("41:2:3:0", "LINESTRING(-74.0500 40.0530, -74.0465 40.0515)", 91.0, True),
        ("42:3:1:0", "LINESTRING(-74.0465 40.0515, -74.0500 40.0500)", 90.0, True),
        ("43:1:4:0", "LINESTRING(-74.0500 40.0500, -74.0460 40.0500)", 84.0, True),
        ("44:4:5:0", "LINESTRING(-74.0460 40.0500, -74.0475 40.0465)", 83.0, False),
        ("45:5:1:0", "LINESTRING(-74.0475 40.0465, -74.0500 40.0500)", 82.0, False),
        ("46:1:6:0", "LINESTRING(-74.0500 40.0500, -74.0500 40.0470)", 76.0, True),
        ("47:6:7:0", "LINESTRING(-74.0500 40.0470, -74.0535 40.0485)", 75.0, False),
        ("48:7:1:0", "LINESTRING(-74.0535 40.0485, -74.0500 40.0500)", 74.0, True),
    ]
    for segment_id, wkt, composite_score, verified in segments:
        _insert_segment(
            db_connection,
            segment_id,
            wkt,
            composite_score=composite_score,
            verified=verified,
        )


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = jwt.encode(
        {
            "user_id": str(user_id),
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        },
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _jaccard_similarity(first: set[str], second: set[str]) -> float:
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def test_routes_suggest_loop_returns_candidates_without_auth(db_connection) -> None:
    _build_loop_graph(db_connection)
    refresh_graph(connection=db_connection)

    client = _client()
    response = client.post(
        "/routes/suggest",
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "mode": "loop",
            "distance_m": 1000,
            "activity": "walk",
            "priority": "highest-rated",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["routes"]) >= 2
    for route in payload["routes"]:
        assert route["segment_ids"]
        assert route["geometry"]["type"] == "LineString"
        assert len(route["geometry"]["coordinates"]) >= 4
        assert route["distance_m"] > 0
        assert route["duration_s"] > 0
        assert route["verified_count"] + route["unverified_count"] == len(route["segment_ids"])

    assert _jaccard_similarity(
        set(payload["routes"][0]["segment_ids"]),
        set(payload["routes"][1]["segment_ids"]),
    ) < 0.5


def test_routes_suggest_requires_end_for_point_modes(db_connection) -> None:
    refresh_graph(connection=db_connection)
    client = _client()

    response = client.post(
        "/routes/suggest",
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "mode": "point-to-destination",
            "distance_m": 1000,
            "activity": "walk",
            "priority": "highest-rated",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "end is required for non-loop routes"


def test_routes_suggest_returns_graceful_error_when_unavailable(db_connection) -> None:
    refresh_graph(connection=db_connection)
    client = _client()

    response = client.post(
        "/routes/suggest",
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "mode": "loop",
            "distance_m": 80000,
            "activity": "walk",
            "priority": "highest-rated",
        },
    )

    assert response.status_code == 400
    assert "No routes available" in response.json()["detail"]


def test_save_route_requires_auth(db_connection) -> None:
    _build_loop_graph(db_connection)
    refresh_graph(connection=db_connection)
    client = _client()

    response = client.post(
        "/routes",
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "mode": "loop",
            "priority": "highest-rated",
            "segment_ids": ["40:1:2:0", "41:2:3:0", "42:3:1:0"],
            "distance_m": 1005.0,
            "duration_s": 718,
            "avg_score": 91.0,
        },
    )

    assert response.status_code == 401


def test_save_route_and_get_history_return_persisted_route(db_connection) -> None:
    user_id = uuid.uuid4()
    _insert_user(db_connection, user_id)
    _build_loop_graph(db_connection)
    refresh_graph(connection=db_connection)

    client = _client()
    suggest_response = client.post(
        "/routes/suggest",
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "mode": "loop",
            "distance_m": 1000,
            "activity": "walk",
            "priority": "highest-rated",
        },
    )

    route = suggest_response.json()["routes"][0]
    save_response = client.post(
        "/routes",
        headers=_auth_headers(user_id),
        json={
            "start": {"lat": 40.05001, "lng": -74.05001},
            "end": None,
            "mode": "loop",
            "priority": "highest-rated",
            "segment_ids": route["segment_ids"],
            "distance_m": route["distance_m"],
            "duration_s": route["duration_s"],
            "avg_score": route["avg_score"],
        },
    )

    assert save_response.status_code == 200
    saved_payload = save_response.json()
    assert saved_payload["route_id"]
    assert saved_payload["mode"] == "loop"
    assert saved_payload["geometry"]["type"] == "LineString"
    assert saved_payload["segment_ids"] == route["segment_ids"]
    assert saved_payload["verified_count"] + saved_payload["unverified_count"] == len(route["segment_ids"])

    history_response = client.get(
        "/users/me/routes",
        headers=_auth_headers(user_id),
    )

    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert len(history_payload["routes"]) == 1
    history_route = history_payload["routes"][0]
    assert history_route["route_id"] == saved_payload["route_id"]
    assert history_route["segment_ids"] == route["segment_ids"]
    assert history_route["geometry"]["type"] == "LineString"
    assert history_route["start"] == {"lat": 40.05001, "lng": -74.05001}
