from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def _auth_header_for_user(user_id: uuid.UUID, *, exp: datetime | None = None) -> dict[str, str]:
    token = jwt.encode(
        {
            "user_id": str(user_id),
            "exp": exp or (datetime.now(timezone.utc) + timedelta(hours=24)),
        },
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_token_and_persists_bcrypt_hash(db_connection) -> None:
    client = _client()

    response = client.post(
        "/auth/register",
        json={"email": "  USER@example.com ", "password": "password123"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["token"]
    assert payload["user"]["email"] == "user@example.com"
    user_id = uuid.UUID(payload["user"]["id"])

    stored_hash = db_connection.execute(
        text("SELECT password_hash FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()
    assert stored_hash != "password123"
    assert stored_hash.startswith("$2")


def test_register_duplicate_email_returns_conflict(db_connection) -> None:
    client = _client()

    first = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert first.status_code == 201

    second = client.post(
        "/auth/register",
        json={"email": "USER@example.com", "password": "password123"},
    )
    assert second.status_code == 409


def test_login_returns_token_for_valid_credentials(db_connection) -> None:
    client = _client()
    register_response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert register_response.status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": " user@example.com ", "password": "password123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token"]
    assert payload["user"]["email"] == "user@example.com"


def test_login_wrong_password_returns_unauthorized(db_connection) -> None:
    client = _client()
    register_response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert register_response.status_code == 201

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrongpass123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_auth_me_returns_current_user_for_valid_token(db_connection) -> None:
    client = _client()
    register_response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    token = register_response.json()["token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "user@example.com"
    assert payload["id"] == register_response.json()["user"]["id"]


def test_auth_me_rejects_malformed_token(db_connection) -> None:
    client = _client()

    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired authorization token"


def test_auth_me_rejects_expired_token(db_connection) -> None:
    client = _client()
    register_response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "password123"},
    )
    user_id = uuid.UUID(register_response.json()["user"]["id"])

    response = client.get(
        "/auth/me",
        headers=_auth_header_for_user(
            user_id,
            exp=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired authorization token"


def test_auth_me_rejects_token_for_missing_user(db_connection) -> None:
    client = _client()

    response = client.get(
        "/auth/me",
        headers=_auth_header_for_user(uuid.uuid4()),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authenticated user not found"
