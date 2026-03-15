from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import networkx as nx
from sqlalchemy import Connection, Engine, text

from app.ingest import get_engine

logger = logging.getLogger(__name__)

_GRAPH_LOCK = threading.Lock()
_GRAPH_CACHE: "GraphCache | None" = None

_DEFAULT_SCORE = 0.0
_DINING_AMENITIES = {
    "restaurant",
    "cafe",
    "bar",
    "pub",
    "fast_food",
    "food_court",
    "biergarten",
    "ice_cream",
}


@dataclass(frozen=True)
class GraphCache:
    graph: nx.MultiDiGraph
    built_at: float
    node_count: int
    edge_count: int
    component_count: int
    build_seconds: float


def get_graph() -> nx.MultiDiGraph:
    cache = _GRAPH_CACHE
    if cache is None:
        cache = refresh_graph()
    return cache.graph


def refresh_graph(
    *,
    engine: Engine | None = None,
    connection: Connection | None = None,
) -> GraphCache:
    """Rebuild the routing graph from the database and swap the cache."""
    start_time = time.monotonic()
    if connection is None:
        engine = engine or get_engine()
        with engine.begin() as connection:
            cache = _build_graph(connection, start_time)
    else:
        cache = _build_graph(connection, start_time)

    with _GRAPH_LOCK:
        global _GRAPH_CACHE
        _GRAPH_CACHE = cache

    return cache


def _build_graph(connection: Connection, start_time: float) -> GraphCache:
    has_pois = _table_exists(connection, "pois")
    near_restaurant_query = "FALSE" if not has_pois else """
        EXISTS (
            SELECT 1
            FROM pois p
            WHERE ST_DWithin(
                s.geometry::geography,
                p.geometry::geography,
                50
            )
            AND (
                p.osm_tags ? 'shop'
                OR (p.osm_tags->>'amenity') = ANY(:amenities)
            )
        )
    """
    restaurant_distance_query = "NULL" if not has_pois else """
        (
            SELECT MIN(ST_Distance(s.geometry::geography, p.geometry::geography))
            FROM pois p
            WHERE
                p.osm_tags ? 'shop'
                OR (p.osm_tags->>'amenity') = ANY(:amenities)
        )
    """

    query = text(
        f"""
        SELECT
            s.id,
            s.composite_score,
            s.verified,
            s.ai_confidence,
            s.osm_tags,
            ST_Length(s.geometry::geography) AS distance_m,
            ST_X(ST_StartPoint(s.geometry)) AS start_lon,
            ST_Y(ST_StartPoint(s.geometry)) AS start_lat,
            ST_X(ST_EndPoint(s.geometry)) AS end_lon,
            ST_Y(ST_EndPoint(s.geometry)) AS end_lat,
            {near_restaurant_query} AS near_restaurant,
            {restaurant_distance_query} AS restaurant_distance_m
        FROM segments s
        """
    )

    params: dict[str, Any] = {}
    if has_pois:
        params["amenities"] = list(_DINING_AMENITIES)

    rows = connection.execute(query, params).mappings().all()

    graph = nx.MultiDiGraph()
    skipped = 0

    for row in rows:
        segment_id = row["id"]
        try:
            u, v = _parse_segment_nodes(segment_id)
        except ValueError:
            skipped += 1
            logger.warning("Skipping segment with unexpected id format: %s", segment_id)
            continue

        start_lat = row["start_lat"]
        start_lon = row["start_lon"]
        end_lat = row["end_lat"]
        end_lon = row["end_lon"]

        if None in (start_lat, start_lon, end_lat, end_lon):
            skipped += 1
            logger.warning("Skipping segment with missing geometry points: %s", segment_id)
            continue

        _ensure_node(graph, u, start_lat, start_lon)
        _ensure_node(graph, v, end_lat, end_lon)

        composite_score = row["composite_score"]
        score_for_weight = _DEFAULT_SCORE if composite_score is None else float(composite_score)
        score_for_weight = max(0.0, min(100.0, score_for_weight))
        weight = 1.0 - (score_for_weight / 100.0)

        osm_tags = row["osm_tags"] or {}
        graph.add_edge(
            u,
            v,
            key=segment_id,
            segment_id=segment_id,
            distance_m=float(row["distance_m"] or 0.0),
            composite_score=composite_score,
            verified=bool(row["verified"]),
            ai_confidence=row["ai_confidence"],
            osm_tags=osm_tags,
            near_restaurant=bool(row["near_restaurant"]),
            restaurant_distance_m=(
                float(row["restaurant_distance_m"])
                if row["restaurant_distance_m"] is not None
                else None
            ),
            is_residential=_is_residential(osm_tags),
            weight=weight,
        )

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    component_count = nx.number_weakly_connected_components(graph)
    build_seconds = time.monotonic() - start_time

    logger.info(
        "Routing graph built with %s nodes, %s edges in %.2fs",
        node_count,
        edge_count,
        build_seconds,
    )
    if skipped:
        logger.warning("Skipped %s segments due to invalid ids", skipped)
    if component_count > 1:
        component_sizes = sorted(
            (len(component) for component in nx.weakly_connected_components(graph)),
            reverse=True,
        )
        logger.warning(
            "Routing graph has %s disconnected components; largest sizes=%s",
            component_count,
            component_sizes[:5],
        )

    return GraphCache(
        graph=graph,
        built_at=time.time(),
        node_count=node_count,
        edge_count=edge_count,
        component_count=component_count,
        build_seconds=build_seconds,
    )


def _ensure_node(graph: nx.MultiDiGraph, node_id: str, lat: float, lon: float) -> None:
    if node_id in graph:
        return
    graph.add_node(node_id, lat=float(lat), lng=float(lon))


def _parse_segment_nodes(segment_id: str) -> tuple[str, str]:
    parts = segment_id.split(":", 3)
    if len(parts) != 4:
        raise ValueError("segment_id is not in expected format")
    _, u, v, _ = parts
    return str(u), str(v)


def _tag_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _tag_in(value: Any, options: set[str]) -> bool:
    return any(tag in options for tag in _tag_values(value))


def _is_residential(osm_tags: dict[str, Any]) -> bool:
    landuse = osm_tags.get("landuse")
    highway = osm_tags.get("highway")
    return _tag_in(landuse, {"residential"}) and _tag_in(
        highway, {"residential", "living_street"}
    )


def _table_exists(connection: Connection, table_name: str) -> bool:
    return (
        connection.execute(
            text("SELECT to_regclass(:table_name)"),
            {"table_name": f"public.{table_name}"},
        )
        .scalar_one()
        is not None
    )
