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

echo "Downgrading Alembic migrations to base..."

docker compose exec -T api alembic -c /app/alembic.ini downgrade base

