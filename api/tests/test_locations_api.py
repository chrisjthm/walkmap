from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.location_search import LocationResult, LocationSearchError
from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_locations_search_returns_normalized_results(monkeypatch) -> None:
    def fake_search(query: str, *, limit: int = 5):
        assert query == "grove street"
        assert limit == 5
        return [
            LocationResult(
                id="nominatim:1",
                label="Grove Street PATH",
                lat=40.7196,
                lng=-74.0431,
                kind="landmark",
                secondary_text="Jersey City, New Jersey",
            ),
        ]

    monkeypatch.setattr(main, "search_locations", fake_search)

    response = _client().get("/locations/search?q=grove%20street")

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "id": "nominatim:1",
                "label": "Grove Street PATH",
                "lat": 40.7196,
                "lng": -74.0431,
                "kind": "landmark",
                "secondary_text": "Jersey City, New Jersey",
            },
        ],
    }


def test_locations_search_returns_empty_for_short_query() -> None:
    response = _client().get("/locations/search?q=ab")

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_locations_search_returns_friendly_error_on_provider_failure(monkeypatch) -> None:
    def fake_search(query: str, *, limit: int = 5):
        raise LocationSearchError("boom")

    monkeypatch.setattr(main, "search_locations", fake_search)

    response = _client().get("/locations/search?q=hamilton%20park")

    assert response.status_code == 503
    assert response.json()["detail"] == "Location search is temporarily unavailable."
