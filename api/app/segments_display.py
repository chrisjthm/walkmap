from __future__ import annotations


def _normalize_highway_value(highway: object) -> str | None:
    if highway is None:
        return None
    if isinstance(highway, str):
        value = highway.strip()
        return value or None
    if isinstance(highway, (list, tuple, set)):
        candidates = [str(item).strip() for item in highway if str(item).strip()]
        if not candidates:
            return None
        # Prefer more specific pedestrian-oriented tags when multiple are present.
        priority = ["footway", "path", "pedestrian", "residential", "living_street"]
        for preferred in priority:
            for candidate in candidates:
                if candidate == preferred:
                    return candidate
        return candidates[0]
    value = str(highway).strip()
    return value or None


def display_name_from_values(name: str | None, highway: object) -> str:
    if name:
        cleaned = str(name).strip()
        if cleaned:
            return cleaned
    key = _normalize_highway_value(highway)
    if key:
            mapping = {
                "residential": "Residential street",
                "footway": "Footway",
                "path": "Path",
                "living_street": "Living street",
                "service": "Service road",
                "pedestrian": "Pedestrian street",
                "track": "Track",
                "cycleway": "Cycleway",
                "steps": "Steps",
            }
            if key in mapping:
                return mapping[key]
            return key.replace("_", " ").replace("-", " ").title()
    return "Unnamed segment"


def display_name_from_osm_tags(osm_tags: dict | None) -> str:
    if not osm_tags:
        return "Unnamed segment"
    return display_name_from_values(osm_tags.get("name"), osm_tags.get("highway"))
