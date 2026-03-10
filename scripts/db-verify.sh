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

echo "Starting services (postgres + api)..."
docker compose up -d --build postgres api

echo "Waiting for postgres to be ready..."
for i in {1..30}; do
  if docker compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then
    echo "ERROR: Postgres did not become ready in time." >&2
    exit 1
  fi
done

echo "Cleaning up stale enum types if no tables exist..."
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'segments') THEN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'route_mode') THEN
      DROP TYPE route_mode;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'route_priority') THEN
      DROP TYPE route_priority;
    END IF;
  END IF;
END $$;
SQL

echo "Running alembic upgrade head..."
./scripts/db-migrate.sh

echo "Checking PostGIS availability..."
POSTGIS_VERSION=$(docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT PostGIS_Version();")
if [ -z "${POSTGIS_VERSION}" ]; then
  echo "ERROR: PostGIS version query failed." >&2
  exit 1
fi

echo "PostGIS: ${POSTGIS_VERSION}"

echo "Running schema and constraint checks..."
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'segments') THEN
    RAISE EXCEPTION 'segments table missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
    RAISE EXCEPTION 'users table missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ratings') THEN
    RAISE EXCEPTION 'ratings table missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'routes') THEN
    RAISE EXCEPTION 'routes table missing';
  END IF;
END $$;

-- Index checks
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_segments_geometry') THEN
    RAISE EXCEPTION 'ix_segments_geometry missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_segments_composite_score') THEN
    RAISE EXCEPTION 'ix_segments_composite_score missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_ratings_segment_id') THEN
    RAISE EXCEPTION 'ix_ratings_segment_id missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_ratings_user_id') THEN
    RAISE EXCEPTION 'ix_ratings_user_id missing';
  END IF;
END $$;

-- Insert a test user
INSERT INTO users (id, email, password_hash)
VALUES ('11111111-1111-1111-1111-111111111111', 'test@example.com', 'hash');

-- Insert a test segment with a LineString geometry
INSERT INTO segments (
  id,
  geometry,
  osm_tags,
  ai_score,
  ai_confidence,
  user_score,
  composite_score,
  verified,
  rating_count,
  vibe_tag_counts,
  last_updated
) VALUES (
  'seg-1',
  ST_GeomFromText('LINESTRING(-74.05 40.72, -74.048 40.721)', 4326),
  '{"highway": "residential"}',
  NULL,
  NULL,
  NULL,
  NULL,
  FALSE,
  0,
  '{}'::jsonb,
  NULL
);

-- Geometry validity check
DO $$
DECLARE
  wkt text;
BEGIN
  SELECT ST_AsText(geometry) INTO wkt FROM segments WHERE id = 'seg-1';
  IF wkt IS NULL OR wkt = '' THEN
    RAISE EXCEPTION 'geometry WKT missing';
  END IF;
END $$;

-- Foreign key constraint check
DO $$
BEGIN
  BEGIN
    INSERT INTO ratings (id, segment_id, user_id, thumbs_up, vibe_tags)
    VALUES ('22222222-2222-2222-2222-222222222222', 'does-not-exist', '11111111-1111-1111-1111-111111111111', TRUE, ARRAY['scenic']);
    RAISE EXCEPTION 'expected FK violation did not occur';
  EXCEPTION WHEN foreign_key_violation THEN
    -- expected
    NULL;
  END;
END $$;

-- Unique constraint check
INSERT INTO ratings (id, segment_id, user_id, thumbs_up, vibe_tags)
VALUES ('33333333-3333-3333-3333-333333333333', 'seg-1', '11111111-1111-1111-1111-111111111111', TRUE, ARRAY['scenic']);

DO $$
BEGIN
  BEGIN
    INSERT INTO ratings (id, segment_id, user_id, thumbs_up, vibe_tags)
    VALUES ('44444444-4444-4444-4444-444444444444', 'seg-1', '11111111-1111-1111-1111-111111111111', FALSE, ARRAY['loud traffic']);
    RAISE EXCEPTION 'expected unique violation did not occur';
  EXCEPTION WHEN unique_violation THEN
    -- expected
    NULL;
  END;
END $$;
SQL

echo "Running alembic downgrade base..."
./scripts/db-downgrade.sh

echo "Verifying tables are dropped..."
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'segments') THEN
    RAISE EXCEPTION 'segments table still exists after downgrade';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
    RAISE EXCEPTION 'users table still exists after downgrade';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ratings') THEN
    RAISE EXCEPTION 'ratings table still exists after downgrade';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'routes') THEN
    RAISE EXCEPTION 'routes table still exists after downgrade';
  END IF;
END $$;
SQL

echo "Running alembic upgrade head again to confirm idempotency..."
./scripts/db-migrate.sh

echo "All DB verification checks passed."
