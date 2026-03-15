from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.ingest import get_engine
from app.routing_graph import refresh_graph
from app.scoring import load_scoring_config, score_segment

DEFAULT_RADIUS_M = 50
DEFAULT_WATER_RADIUS_M = 300
DEFAULT_PARK_RADIUS_M = 150


def run_batch_scoring(
    batch_size: int = 200,
    limit: int | None = None,
    radius_m: int = DEFAULT_RADIUS_M,
    engine: Engine | None = None,
    connection: Connection | None = None,
) -> int:
    """Score unscored segments in batches and persist results."""
    weights = load_scoring_config()
    processed = 0
    connection_provided = connection is not None
    if connection is None:
        engine = engine or get_engine()
        with engine.begin() as connection:
            processed = _score_batches(connection, weights, batch_size, limit, radius_m)
    else:
        processed = _score_batches(connection, weights, batch_size, limit, radius_m)

    if processed:
        if connection_provided:
            refresh_graph(connection=connection)
        else:
            refresh_graph(engine=engine)
    return processed


def _score_batches(
    connection: Connection,
    weights: dict[str, Any],
    batch_size: int,
    limit: int | None,
    radius_m: int,
) -> int:
    total_remaining = _count_unscored(connection)
    if total_remaining == 0:
        return 0

    has_pois = _pois_table_exists(connection)
    has_water = _water_table_exists(connection)
    has_parks = _parks_table_exists(connection)
    has_distance_m = _segments_has_distance_m(connection)
    distance_expression = (
        "distance_m" if has_distance_m else "ST_Length(geometry::geography) AS distance_m"
    )
    processed = 0

    while True:
        remaining_limit = None if limit is None else max(limit - processed, 0)
        if remaining_limit == 0:
            break
        fetch_limit = batch_size if remaining_limit is None else min(batch_size, remaining_limit)

        rows = connection.execute(
            text(
                f"""
                SELECT id, osm_tags, {distance_expression}, ST_AsEWKB(geometry) AS geometry
                FROM segments
                WHERE ai_score IS NULL
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": fetch_limit},
        ).mappings().all()

        if not rows:
            break

        updates: list[dict[str, Any]] = []
        for row in rows:
            nearby_pois = (
                _fetch_nearby_pois(connection, row["geometry"], radius_m)
                if has_pois
                else []
            )
            water_distance_m = None
            if has_water:
                water_distance_m = _fetch_water_distance_m(
                    connection,
                    row["geometry"],
                    DEFAULT_WATER_RADIUS_M,
                )
            park_distance_m = None
            if has_parks:
                park_distance_m = _fetch_park_distance_m(
                    connection,
                    row["geometry"],
                    DEFAULT_PARK_RADIUS_M,
                )
            result = score_segment(
                row["osm_tags"],
                nearby_pois,
                weights,
                water_distance_m=water_distance_m,
                park_distance_m=park_distance_m,
                distance_m=row["distance_m"],
            )
            updates.append(
                {
                    "id": row["id"],
                    "ai_score": result.score,
                    "ai_confidence": result.confidence,
                    "composite_score": result.score,
                    "factors": json.dumps(result.factors),
                }
            )

        connection.execute(
            text(
                """
                UPDATE segments
                SET ai_score = :ai_score,
                    ai_confidence = :ai_confidence,
                    composite_score = :composite_score,
                    factors = CAST(:factors AS jsonb),
                    last_updated = now()
                WHERE id = :id
                """
            ),
            updates,
        )

        processed += len(updates)
        print(f"Scored {processed}/{total_remaining} segments")

    return processed


def _count_unscored(connection: Connection) -> int:
    return connection.execute(
        text("SELECT COUNT(*) FROM segments WHERE ai_score IS NULL")
    ).scalar_one()


def _pois_table_exists(connection: Connection) -> bool:
    return (
        connection.execute(text("SELECT to_regclass('public.pois')"))
        .scalar_one()
        is not None
    )


def _water_table_exists(connection: Connection) -> bool:
    return (
        connection.execute(text("SELECT to_regclass('public.water_features')"))
        .scalar_one()
        is not None
    )


def _parks_table_exists(connection: Connection) -> bool:
    return (
        connection.execute(text("SELECT to_regclass('public.parks')"))
        .scalar_one()
        is not None
    )


def _segments_has_distance_m(connection: Connection) -> bool:
    return connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'segments'
                  AND column_name = 'distance_m'
            )
            """
        )
    ).scalar_one()


def _fetch_nearby_pois(connection: Connection, geometry_wkb: bytes, radius_m: int) -> list[dict]:
    rows = connection.execute(
        text(
            """
            SELECT osm_tags
            FROM pois
            WHERE ST_DWithin(
                geometry::geography,
                ST_GeomFromEWKB(:geom)::geography,
                :radius_m
            )
            """
        ),
        {"geom": geometry_wkb, "radius_m": radius_m},
    ).mappings().all()
    return [row["osm_tags"] for row in rows]


def _fetch_water_distance_m(
    connection: Connection, geometry_wkb: bytes, radius_m: int
) -> float | None:
    row = connection.execute(
        text(
            """
            WITH midpoint AS (
                SELECT ST_LineInterpolatePoint(ST_GeomFromEWKB(:geom), 0.5) AS geom
            )
            SELECT ST_Distance(w.geometry::geography, m.geom::geography) AS distance_m
            FROM water_features w
            CROSS JOIN midpoint m
            WHERE ST_DWithin(w.geometry::geography, m.geom::geography, :radius_m)
            ORDER BY distance_m
            LIMIT 1
            """
        ),
        {"geom": geometry_wkb, "radius_m": radius_m},
    ).mappings().first()
    if row is None:
        return None
    return float(row["distance_m"])


def _fetch_park_distance_m(
    connection: Connection, geometry_wkb: bytes, radius_m: int
) -> float | None:
    row = connection.execute(
        text(
            """
            WITH midpoint AS (
                SELECT ST_LineInterpolatePoint(ST_GeomFromEWKB(:geom), 0.5) AS geom
            )
            SELECT ST_Distance(p.geometry::geography, m.geom::geography) AS distance_m
            FROM parks p
            CROSS JOIN midpoint m
            WHERE (
                p.osm_tags ->> 'leisure' IN ('park', 'playground')
                OR p.osm_tags ->> 'landuse' = 'grass'
            )
            AND ST_DWithin(p.geometry::geography, m.geom::geography, :radius_m)
            ORDER BY distance_m
            LIMIT 1
            """
        ),
        {"geom": geometry_wkb, "radius_m": radius_m},
    ).mappings().first()
    if row is None:
        return None
    return float(row["distance_m"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch score unscored segments")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--radius-m", type=int, default=DEFAULT_RADIUS_M)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    processed = run_batch_scoring(
        batch_size=args.batch_size,
        limit=args.limit,
        radius_m=args.radius_m,
    )
    print(f"Finished scoring {processed} segments")


if __name__ == "__main__":
    main()
