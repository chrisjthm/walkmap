#!/usr/bin/env bash
set -euo pipefail

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
sleep 15
./scripts/db-migrate.sh
./scripts/ingest-osm.sh
./scripts/score-batch.sh
