from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.ingest import get_engine
from app.scoring import load_scoring_config, score_segment

DEFAULT_RADIUS_M = 50


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
    if connection is None:
        engine = engine or get_engine()
        with engine.begin() as connection:
            processed = _score_batches(connection, weights, batch_size, limit, radius_m)
    else:
        processed = _score_batches(connection, weights, batch_size, limit, radius_m)

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
    processed = 0

    while True:
        remaining_limit = None if limit is None else max(limit - processed, 0)
        if remaining_limit == 0:
            break
        fetch_limit = batch_size if remaining_limit is None else min(batch_size, remaining_limit)

        rows = connection.execute(
            text(
                """
                SELECT id, osm_tags, ST_AsEWKB(geometry) AS geometry
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
            result = score_segment(row["osm_tags"], nearby_pois, weights)
            updates.append(
                {
                    "id": row["id"],
                    "ai_score": result.score,
                    "ai_confidence": result.confidence,
                    "composite_score": result.score,
                }
            )

        connection.execute(
            text(
                """
                UPDATE segments
                SET ai_score = :ai_score,
                    ai_confidence = :ai_confidence,
                    composite_score = :composite_score,
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


def _fetch_nearby_pois(connection: Connection, geometry_wkb: bytes, radius_m: int) -> list[dict]:
    rows = connection.execute(
        text(
            """
            SELECT tags
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
    return [row["tags"] for row in rows]


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
