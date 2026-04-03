from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app


def test_lifespan_tolerates_transient_graph_refresh_failures() -> None:
    with patch("app.main.refresh_graph", side_effect=OperationalError("stmt", {}, Exception("boom"))):
        with TestClient(app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
