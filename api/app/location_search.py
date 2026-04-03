from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.ingest import DEFAULT_BBOX

LocationKind = Literal["address", "business", "landmark", "coordinate", "other"]

_MIN_QUERY_LENGTH = 3
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 8
_USER_AGENT = "walkmap/0.0.1 (planner-search)"
_ADDRESS_CLASSES = {
    "building",
    "place",
    "boundary",
    "highway",
    "railway",
}
_BUSINESS_CLASSES = {
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "office",
}
_LANDMARK_TYPES = {
    "park",
    "station",
    "hotel",
    "museum",
    "library",
    "playground",
}


class LocationSearchError(RuntimeError):
    """Raised when an upstream location search provider fails."""


@dataclass(frozen=True)
class LocationResult:
    id: str
    label: str
    lat: float
    lng: float
    kind: LocationKind
    secondary_text: str | None = None


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def should_search_query(query: str) -> bool:
    return len(normalize_query(query)) >= _MIN_QUERY_LENGTH


def search_locations(query: str, *, limit: int = _DEFAULT_LIMIT) -> list[LocationResult]:
    normalized_query = normalize_query(query)
    if not should_search_query(normalized_query):
        return []

    response = _search_nominatim(normalized_query, limit=min(max(1, limit), _MAX_LIMIT))
    return [_normalize_nominatim_result(item) for item in response]


def _search_nominatim(query: str, limit: int) -> list[dict[str, Any]]:
    base_url = os.environ.get(
        "GEOCODER_BASE_URL",
        "https://nominatim.openstreetmap.org/search",
    )
    timeout_s = float(os.environ.get("GEOCODER_TIMEOUT_S", "5"))
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": limit,
        "viewbox": _nominatim_viewbox(),
        "bounded": 1,
    }

    try:
        with httpx.Client(timeout=timeout_s, headers={"User-Agent": _USER_AGENT}) as client:
            response = client.get(base_url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LocationSearchError("Location search is temporarily unavailable.") from exc

    payload = response.json()
    if not isinstance(payload, list):
        raise LocationSearchError("Location search returned an unexpected response.")
    return payload


def _nominatim_viewbox() -> str:
    west = DEFAULT_BBOX["west"]
    north = DEFAULT_BBOX["north"]
    east = DEFAULT_BBOX["east"]
    south = DEFAULT_BBOX["south"]
    return f"{west},{north},{east},{south}"


def _normalize_nominatim_result(item: dict[str, Any]) -> LocationResult:
    lat = float(item["lat"])
    lng = float(item["lon"])
    display_name = str(item.get("display_name") or f"{lat:.5f}, {lng:.5f}")
    label, secondary_text = _label_and_secondary_text(item, display_name)
    result_id = str(item.get("place_id") or display_name)
    return LocationResult(
        id=f"nominatim:{result_id}",
        label=label,
        lat=lat,
        lng=lng,
        kind=_classify_nominatim_result(item),
        secondary_text=secondary_text,
    )


def _label_and_secondary_text(item: dict[str, Any], display_name: str) -> tuple[str, str | None]:
    kind = _classify_nominatim_result(item)
    if kind == "address":
        address = item.get("address")
        if isinstance(address, dict):
            house_number = str(address.get("house_number") or "").strip()
            road = str(address.get("road") or address.get("pedestrian") or address.get("footway") or "").strip()
            if house_number and road:
                locality = _join_nonempty(
                    [
                        address.get("suburb"),
                        address.get("city") or address.get("town") or address.get("village"),
                        address.get("state"),
                    ]
                )
                return f"{house_number} {road}", locality or None
            if road:
                locality = _join_nonempty(
                    [
                        address.get("suburb"),
                        address.get("city") or address.get("town") or address.get("village"),
                        address.get("state"),
                    ]
                )
                return road, locality or None
    return _split_display_name(display_name)


def _split_display_name(display_name: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in display_name.split(",") if part.strip()]
    if not parts:
        return display_name, None
    label = parts[0]
    secondary = ", ".join(parts[1:3]) if len(parts) > 1 else None
    return label, secondary


def _join_nonempty(parts: list[object]) -> str:
    return ", ".join(
        str(part).strip()
        for part in parts
        if part is not None and str(part).strip()
    )


def _classify_nominatim_result(item: dict[str, Any]) -> LocationKind:
    item_class = str(item.get("class") or "").lower()
    item_type = str(item.get("type") or "").lower()
    category = str(item.get("category") or "").lower()
    addresstype = str(item.get("addresstype") or "").lower()

    if item_class in _BUSINESS_CLASSES or category in _BUSINESS_CLASSES:
        return "business"
    if item_type in _LANDMARK_TYPES:
        return "landmark"
    if item_class in _ADDRESS_CLASSES or addresstype:
        return "address"
    return "other"
