#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not on PATH." >&2
  exit 1
fi

echo "Stopping containers and removing project volumes..."
docker compose down -v --remove-orphans

if [ "${1:-}" = "--prune" ]; then
  echo "Pruning dangling images and build cache..."
  docker image prune -f
  docker builder prune -f
fi

echo "Teardown complete."
