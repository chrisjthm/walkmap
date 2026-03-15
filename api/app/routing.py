from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import networkx as nx

from app.routing_graph import get_graph

_DISTANCE_TIEBREAKER_PER_M = 0.0001
_ALT_CANDIDATE_SEEDS = (0, 7, 19, 43, 71, 101)
_ALT_PERTURBATION_MAX = 0.12
_OVERLAP_PENALTY = 2.5
_MIN_ROUTE_WEIGHT = 0.01
_EARTH_RADIUS_M = 6_371_000.0

_PEDESTRIAN_EXCLUDED_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
}


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lng: float


@dataclass(frozen=True)
class RouteCandidate:
    segment_ids: list[str]
    node_ids: list[str]
    distance_m: float
    avg_score: float
    verified_count: int
    unverified_count: int
    near_restaurant_count: int
    avg_restaurant_distance_m: float | None
    residential_count: int
    snapped_start: Coordinate
    snapped_end: Coordinate


def suggest_point_to_point_routes(
    start: Coordinate,
    end: Coordinate,
    *,
    priority: str = "highest-rated",
    candidate_count: int = 3,
) -> list[RouteCandidate]:
    graph = get_graph()
    if graph.number_of_nodes() == 0:
        return []
    if math.isclose(start.lat, end.lat) and math.isclose(start.lng, end.lng):
        return []

    reachability_graph = _build_search_graph(
        graph,
        priority="highest-rated",
        penalized_segment_ids=set(),
        seed=0,
    )
    start_node, end_node = _select_reachable_node_pair(
        graph,
        reachability_graph,
        start,
        end,
    )
    if start_node == end_node:
        return []

    candidates: list[RouteCandidate] = []
    used_segment_sets: list[set[str]] = []

    for seed in _ALT_CANDIDATE_SEEDS:
        projected = _build_search_graph(
            graph,
            priority=priority,
            penalized_segment_ids=set().union(*used_segment_sets) if used_segment_sets else set(),
            seed=seed,
        )
        try:
            node_path = nx.astar_path(
                projected,
                start_node,
                end_node,
                heuristic=lambda _a, _b: 0.0,
                weight="weight",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

        candidate = _candidate_from_path(graph, projected, node_path)
        if not candidate.segment_ids:
            continue

        segment_set = set(candidate.segment_ids)
        if any(_jaccard_similarity(segment_set, existing) >= 0.5 for existing in used_segment_sets):
            continue

        candidates.append(candidate)
        used_segment_sets.append(segment_set)
        if len(candidates) >= max(1, min(candidate_count, 3)):
            break

    return candidates


def snap_coordinate_to_node(graph: nx.MultiDiGraph, coordinate: Coordinate) -> str:
    nearest_nodes = _nearest_nodes(graph, coordinate, limit=1)
    if not nearest_nodes:
        raise nx.NodeNotFound("routing graph has no nodes with coordinates")
    return nearest_nodes[0][0]


def _build_search_graph(
    graph: nx.MultiDiGraph,
    *,
    priority: str,
    penalized_segment_ids: set[str],
    seed: int,
) -> nx.DiGraph:
    projected = nx.DiGraph()
    projected.add_nodes_from(graph.nodes(data=True))
    rng = random.Random(seed)

    for u, v, edge_key, edge_data in graph.edges(keys=True, data=True):
        if not _is_pedestrian_navigable(edge_data):
            continue

        weight = _effective_weight(edge_data, priority=priority)
        weight += float(edge_data.get("distance_m") or 0.0) * _DISTANCE_TIEBREAKER_PER_M

        if edge_key in penalized_segment_ids:
            weight += _OVERLAP_PENALTY
        elif seed:
            weight *= 1.0 + rng.uniform(0.0, _ALT_PERTURBATION_MAX)

        current = projected.get_edge_data(u, v)
        if current is None or weight < current["weight"]:
            projected.add_edge(
                u,
                v,
                weight=weight,
                segment_id=edge_key,
                edge_attrs=edge_data,
            )

    return projected


def _candidate_from_path(
    graph: nx.MultiDiGraph,
    projected: nx.DiGraph,
    node_path: list[str],
) -> RouteCandidate:
    segment_ids: list[str] = []
    distance_m = 0.0
    total_score = 0.0
    verified_count = 0
    unverified_count = 0
    near_restaurant_count = 0
    restaurant_distance_total_m = 0.0
    restaurant_distance_count = 0
    residential_count = 0

    for u, v in zip(node_path, node_path[1:]):
        projected_edge = projected.get_edge_data(u, v)
        if projected_edge is None:
            continue

        segment_id = projected_edge["segment_id"]
        edge_data = graph[u][v][segment_id]

        segment_ids.append(segment_id)
        distance_m += float(edge_data.get("distance_m") or 0.0)
        total_score += float(edge_data.get("composite_score") or 0.0)

        if edge_data.get("verified"):
            verified_count += 1
        else:
            unverified_count += 1
        if edge_data.get("near_restaurant"):
            near_restaurant_count += 1
        restaurant_distance_m = edge_data.get("restaurant_distance_m")
        if restaurant_distance_m is not None:
            restaurant_distance_total_m += float(restaurant_distance_m)
            restaurant_distance_count += 1
        if edge_data.get("is_residential"):
            residential_count += 1

    if not segment_ids:
        return RouteCandidate(
            segment_ids=[],
            node_ids=node_path,
            distance_m=0.0,
            avg_score=0.0,
            verified_count=0,
            unverified_count=0,
            near_restaurant_count=0,
            avg_restaurant_distance_m=None,
            residential_count=0,
            snapped_start=_coordinate_from_node(graph, node_path[0]),
            snapped_end=_coordinate_from_node(graph, node_path[-1]),
        )

    return RouteCandidate(
        segment_ids=segment_ids,
        node_ids=node_path,
        distance_m=distance_m,
        avg_score=total_score / len(segment_ids),
        verified_count=verified_count,
        unverified_count=unverified_count,
        near_restaurant_count=near_restaurant_count,
        avg_restaurant_distance_m=(
            restaurant_distance_total_m / restaurant_distance_count
            if restaurant_distance_count
            else None
        ),
        residential_count=residential_count,
        snapped_start=_coordinate_from_node(graph, node_path[0]),
        snapped_end=_coordinate_from_node(graph, node_path[-1]),
    )


def _coordinate_from_node(graph: nx.MultiDiGraph, node_id: str) -> Coordinate:
    node = graph.nodes[node_id]
    return Coordinate(lat=float(node["lat"]), lng=float(node["lng"]))


def _effective_weight(edge_data: dict[str, Any], *, priority: str) -> float:
    base_weight = max(_MIN_ROUTE_WEIGHT, float(edge_data.get("weight") or 0.0))

    if priority == "highest-rated":
        return base_weight
    if priority == "dining":
        restaurant_distance_m = edge_data.get("restaurant_distance_m")
        if restaurant_distance_m is None:
            return base_weight * 1.1
        if restaurant_distance_m <= 50.0:
            return base_weight * 0.55
        if restaurant_distance_m <= 150.0:
            return base_weight * 0.8
        return base_weight * 1.1
    if priority == "residential":
        return base_weight * (0.15 if edge_data.get("is_residential") else 1.5)
    if priority == "explore":
        if not edge_data.get("verified"):
            confidence = float(edge_data.get("ai_confidence") or 0.0)
            confidence_bonus = min(max(confidence, 0.0), 1.0) * 0.35
            return base_weight * max(0.45, 0.8 - confidence_bonus)
        return base_weight * 1.1
    return base_weight


def _select_reachable_node_pair(
    graph: nx.MultiDiGraph,
    projected: nx.DiGraph,
    start: Coordinate,
    end: Coordinate,
    *,
    nearest_limit: int = 10,
) -> tuple[str, str]:
    start_candidates = _nearest_nodes(graph, start, limit=nearest_limit)
    end_candidates = _nearest_nodes(graph, end, limit=nearest_limit)

    if not start_candidates or not end_candidates:
        raise nx.NodeNotFound("routing graph has no nodes with coordinates")

    best_pair: tuple[str, str] | None = None
    best_distance = math.inf

    for start_node, start_distance in start_candidates:
        for end_node, end_distance in end_candidates:
            if start_node == end_node:
                continue
            if not nx.has_path(projected, start_node, end_node):
                continue

            total_distance = start_distance + end_distance
            if total_distance < best_distance:
                best_pair = (start_node, end_node)
                best_distance = total_distance

    if best_pair is not None:
        return best_pair

    for start_node, _start_distance in start_candidates:
        for end_node, _end_distance in end_candidates:
            if start_node != end_node:
                return start_node, end_node

    return start_candidates[0][0], end_candidates[0][0]


def _nearest_nodes(
    graph: nx.MultiDiGraph,
    coordinate: Coordinate,
    *,
    limit: int,
) -> list[tuple[str, float]]:
    distances: list[tuple[str, float]] = []

    for node_id, data in graph.nodes(data=True):
        lat = data.get("lat")
        lng = data.get("lng")
        if lat is None or lng is None:
            continue

        distance = _haversine_m(coordinate.lat, coordinate.lng, float(lat), float(lng))
        distances.append((str(node_id), distance))

    distances.sort(key=lambda item: item[1])
    return distances[:limit]


def _is_pedestrian_navigable(edge_data: dict[str, Any]) -> bool:
    osm_tags = edge_data.get("osm_tags") or {}
    highway = osm_tags.get("highway")
    if highway is None:
        return True
    if isinstance(highway, list):
        return all(tag not in _PEDESTRIAN_EXCLUDED_HIGHWAYS for tag in highway)
    return str(highway) not in _PEDESTRIAN_EXCLUDED_HIGHWAYS


def _jaccard_similarity(first: set[str], second: set[str]) -> float:
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def _haversine_m(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lng = math.radians(lng_b - lng_a)

    sin_lat = math.sin(delta_lat / 2.0)
    sin_lng = math.sin(delta_lng / 2.0)
    haversine = sin_lat * sin_lat + math.cos(lat_a_rad) * math.cos(lat_b_rad) * sin_lng * sin_lng
    arc = 2.0 * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))
    return _EARTH_RADIUS_M * arc
