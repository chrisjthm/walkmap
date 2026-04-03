#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Create it from .env.example." >&2
  exit 1
fi

# Load env vars for this script run
set -a
# shellcheck disable=SC1091
. ./.env
set +a

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not on PATH." >&2
  exit 1
fi

echo "Running Alembic migrations..."
for _ in {1..30}; do
  if docker compose exec -T api alembic -c /app/alembic.ini upgrade head; then
    exit 0
  fi
  sleep 2
done

echo "ERROR: Alembic migrations did not succeed after repeated retries." >&2
exit 1
