#!/usr/bin/env bash
set -euo pipefail

wait_for_postgres() {
  for _ in {1..30}; do
    if docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "ERROR: Postgres did not become ready in time." >&2
  exit 1
}

wait_for_api() {
  for _ in {1..30}; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "ERROR: API did not become healthy in time." >&2
  exit 1
}

wait_for_real_segment_data() {
  for _ in {1..30}; do
    counts="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
      "SELECT COUNT(*) || ',' || COUNT(*) FILTER (WHERE ai_score IS NOT NULL) FROM segments;")"
    segment_count="${counts%%,*}"
    scored_count="${counts##*,}"

    if [[ "${segment_count:-0}" =~ ^[0-9]+$ ]] && [[ "${scored_count:-0}" =~ ^[0-9]+$ ]] \
      && (( segment_count >= 500 )) && (( scored_count >= 500 )); then
      echo "Verified restored dataset: ${segment_count} segments, ${scored_count} scored."
      return 0
    fi

    sleep 2
  done

  echo "ERROR: Restored dataset did not reach expected size in time." >&2
  exit 1
}

if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Create it from .env.example." >&2
  exit 1
fi

# Ensure compose uses the repo's container-safe env values even if the caller
# already exported host-oriented variables for local test commands.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

docker compose up --build -d
wait_for_postgres
./scripts/db-migrate.sh
./scripts/ingest-osm.sh
./scripts/score-batch.sh
wait_for_real_segment_data

echo "Restarting API to rebuild in-memory graph from restored data..."
docker compose restart api
wait_for_api
