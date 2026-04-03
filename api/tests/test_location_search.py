from __future__ import annotations

import httpx
import pytest

from app.location_search import (
    LocationSearchError,
    normalize_query,
    search_locations,
    should_search_query,
)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "upstream error",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


def test_should_search_query_requires_three_characters() -> None:
    assert should_search_query("ab") is False
    assert should_search_query("abc") is True
    assert should_search_query("  grove street  ") is True


def test_normalize_query_collapses_whitespace() -> None:
    assert normalize_query("  grove   street path  ") == "grove street path"


def test_search_locations_returns_empty_for_short_queries(monkeypatch) -> None:
    get = pytest.fail
    monkeypatch.setattr(httpx.Client, "get", get, raising=False)

    assert search_locations("ab") == []


def test_search_locations_normalizes_mixed_results(monkeypatch) -> None:
    payload = [
        {
            "place_id": 101,
            "lat": "40.7196",
            "lon": "-74.0431",
            "display_name": "Grove Street PATH, Jersey City, New Jersey, United States",
            "class": "railway",
            "type": "station",
            "addresstype": "railway",
        },
        {
            "place_id": 202,
            "lat": "40.7218",
            "lon": "-74.0474",
            "display_name": "Razza, Jersey City, New Jersey, United States",
            "class": "amenity",
            "type": "restaurant",
            "addresstype": "amenity",
        },
        {
            "place_id": 303,
            "lat": "40.7163208",
            "lon": "-74.042669",
            "display_name": "201, Marin Boulevard, Newport, Jersey City, New Jersey, 07302, United States",
            "class": "place",
            "type": "house",
            "addresstype": "house_number",
            "address": {
                "house_number": "201",
                "road": "Marin Boulevard",
                "suburb": "Newport",
                "city": "Jersey City",
                "state": "New Jersey",
            },
        },
    ]

    def fake_get(self, url, params):
        assert "search" in url
        assert params["q"] == "grove street"
        assert params["viewbox"] == "-74.06,40.7282,-74.015,40.708"
        assert params["bounded"] == 1
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    results = search_locations("  grove   street ")

    assert [result.label for result in results] == [
        "Grove Street PATH",
        "Razza",
        "201 Marin Boulevard",
    ]
    assert [result.kind for result in results] == ["landmark", "business", "address"]
    assert results[0].secondary_text == "Jersey City, New Jersey"
    assert results[1].lat == 40.7218
    assert results[1].lng == -74.0474
    assert results[2].secondary_text == "Newport, Jersey City, New Jersey"


def test_search_locations_raises_friendly_error_on_provider_failure(monkeypatch) -> None:
    def fake_get(self, url, params):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with pytest.raises(LocationSearchError):
        search_locations("hamilton park")
