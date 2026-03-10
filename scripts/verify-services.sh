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

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is not installed or not on PATH." >&2
  exit 1
fi

echo "Checking docker compose services..."

docker compose ps --status running

API_URL="${API_URL:-http://localhost:8000/health}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"

echo "Checking API health at ${API_URL}..."
if ! curl -fsS "${API_URL}" >/tmp/walkmap-api-health.json; then
  echo "ERROR: API health check failed." >&2
  exit 1
fi

if ! grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' /tmp/walkmap-api-health.json; then
  echo "ERROR: API health response did not include status=ok." >&2
  cat /tmp/walkmap-api-health.json >&2
  exit 1
fi

echo "Checking frontend at ${FRONTEND_URL}..."
if ! curl -fsS "${FRONTEND_URL}" >/tmp/walkmap-frontend.html; then
  echo "ERROR: Frontend check failed." >&2
  exit 1
fi

if ! grep -qi "Walkmap" /tmp/walkmap-frontend.html; then
  echo "ERROR: Frontend response did not include expected title." >&2
  exit 1
fi

echo "Checking PostGIS availability..."
POSTGIS_VERSION=$(docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT PostGIS_Version();" || true)
if [ -z "${POSTGIS_VERSION}" ]; then
  echo "ERROR: PostGIS version query failed." >&2
  exit 1
fi

echo "PostGIS: ${POSTGIS_VERSION}"

echo "All checks passed."
