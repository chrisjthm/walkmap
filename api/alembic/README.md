# Alembic Migrations

This directory contains the Alembic configuration and migration scripts for the database schema.

## What Alembic Does

Alembic is a migration tool for SQLAlchemy. It lets us version schema changes over time, so every environment can be upgraded (or downgraded) to the same database structure in a repeatable way.

## How It’s Wired Here

- `api/alembic.ini` points Alembic at this folder.
- `api/alembic/env.py` loads `DATABASE_URL` from the environment and imports metadata from `app.db.models`.
- `api/alembic/versions/` holds migration scripts, applied in order.

## Daily Use

Run migrations in the running API container:

```bash
./scripts/db-migrate.sh
```

Downgrade to base:

```bash
./scripts/db-downgrade.sh
```

Run the full verification suite (upgrade, constraints, downgrade, idempotency):

```bash
./scripts/db-verify.sh
```

## How To Make Schema Changes

1. Update the SQLAlchemy models in `api/app/db/models.py`.
2. Create a new migration file under `api/alembic/versions/`.
   - Keep it small and focused.
   - Use explicit `op.create_table`, `op.add_column`, `op.create_index`, etc.
3. If you add new Postgres `ENUM` types:
   - Create them in the migration with `postgresql.ENUM(...).create(bind, checkfirst=True)`.
   - In table definitions, set `create_type=False` to avoid duplicate type creation.
4. If you add new PostGIS geometry columns, use `geoalchemy2.Geometry` with SRID 4326.
5. Verify locally with `./scripts/db-verify.sh`.

## Notes and Conventions

- Migrations are the source of truth for schema changes, not direct SQL against the DB.
- Avoid editing old migrations once they’ve been shared or applied.
- Keep naming stable for enums and indexes.
- Use `server_default` for non-nullable columns when backfilling on existing tables.
