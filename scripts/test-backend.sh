#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env file not found." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if [ -z "${POSTGRES_DB:-}" ] || [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "ERROR: POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD must be set in .env." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "ERROR: .venv not found. Create it first with:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  source .venv/bin/activate" >&2
  echo "  pip install -r api/requirements-dev.txt" >&2
  exit 1
fi

export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"

echo "Using DATABASE_URL=${DATABASE_URL}"
echo "Running backend tests..."

cd api
../.venv/bin/pytest tests "$@"
