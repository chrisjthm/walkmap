# Walkmap

Walkmap is a web app for planning urban walks and runs optimized for route experience, not just speed. The MVP stack includes:

- `postgres`: PostgreSQL 16 + PostGIS
- `api`: FastAPI backend
- `frontend`: React + Vite frontend

## Local Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)

### Run tests

Set up virtual environment and install dependencies

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

Run python app tests:

```bash
cd api
pytest
```

Run python app linting:

```bash
cd api
ruff check .
```

Run frontend linting:

```bash
cd frontend
npm run lint
```

### 1. Configure environment

Create a local env file from the template:

```bash
touch .env
```

Then edit `.env` values as needed (especially `JWT_SECRET` and `MAPBOX_TOKEN`).

### 2. Start all services

```bash
docker compose up --build
```

This starts:

- Postgres/PostGIS on `localhost:5432`
- API on `http://localhost:8000`
- Frontend on `http://localhost:5173`

Alternatively, you can use the startup script:
```bash
./scripts/startup.sh
```

### 3. Verify services

- API health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

- PostGIS check:

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT PostGIS_Version();"
```

Alternatively, you can run the verify services script:
```bash
./scripts/verify-services.sh
```

### 4. Stop services

```bash
docker compose down
```

To also remove volumes:

```bash
docker compose down -v
```

Alternatively, you can run the teardown script:
```bash
./scripts/teardown.sh
```

## Development Notes

- API hot reload is enabled via `uvicorn --reload`.
- Frontend hot reload is enabled by Vite.
- Postgres data persists in the `postgres_data` Docker volume across restarts.
- If `.env` is missing or required variables are unset, Compose fails fast with a clear error.

## Database Migrations

Run Alembic migrations in the API container:

```bash
./scripts/db-migrate.sh
```

To downgrade back to base:

```bash
./scripts/db-downgrade.sh
```

To run the A2 verification checks (upgrade, schema checks, constraints, downgrade, idempotency):

```bash
./scripts/db-verify.sh
```

## Running DB Tests

Some tests require a running Postgres/PostGIS instance and will be skipped if
`DATABASE_URL` is not set. To run the full test suite:

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}
./scripts/db-migrate.sh
cd api && pytest
```

## Railway Backend Deployment

The backend is deployed on Railway as:

- [`api/Dockerfile`](./api/Dockerfile) includes the Alembic files needed for deploy-time migrations and defaults to a production-safe `uvicorn` command that respects Railway's `PORT`.
- [`api/railway.toml`](./api/railway.toml) sets the pre-deploy migration command, start command, healthcheck path, and restart policy for Railway.
- a Railway API service that deploys from the `/api` subdirectory
- a separate PostGIS service on Railway private networking

Railway runs `alembic upgrade head` before starting the FastAPI app.

### Repeatable deploy

Deploy the API service from the `api` directory:

```bash
cd /path/to/walkmap
railway up api --service walkmap --path-as-root -d -m "Deploy API from /api root"
```

If Railway auto-deploy is enabled, pushes to the tracked branch can replace the manual CLI deploy.

### Disable / Re-enable

To fully disable the Railway deployment and avoid ongoing compute cost:

1. Remove the current API deployment:

```bash
cd /path/to/walkmap
railway down -s walkmap -y
```

2. Remove the current PostGIS deployment:

```bash
railway down -s walkmap-db -y
```

3. If you do not need to preserve database contents, delete the Railway volume from the dashboard.

The volume is a project-level resource, not a separate service. In the Railway dashboard, open the project, find `Volumes`, and delete `walkmap-db-volume`.

4. If you want to prevent future code pushes from bringing the API back up, disconnect the GitHub source for the `walkmap` service in the Railway dashboard.

To re-enable the deployment later:

1. Recreate or reattach the PostGIS volume if it was deleted:

```bash
cd /path/to/walkmap
railway volume add --mount-path /var/lib/postgresql/data
```

If the volume is recreated from scratch, ensure the `walkmap-db` service still has `PGDATA=/var/lib/postgresql/data/pgdata` set so Postgres initializes inside a subdirectory on the mounted volume.
2. Ensure the `walkmap-db` service still has the expected Postgres/PostGIS configuration and environment variables.
3. Deploy the API again with:

```bash
cd /path/to/walkmap
railway up api --service walkmap --path-as-root -d -m "Deploy API from /api root"
```

4. If the database was reset or recreated, rerun the data refresh jobs below to repopulate and rescore production data.

### Data refresh jobs

When production data needs to be refreshed, trigger the admin jobs:

```bash
curl -X POST https://<railway-url>/admin/ingest/osm
curl -X POST https://<railway-url>/admin/score/batch
```

Use the ingest job to reload source map data. Use the batch scoring job when new or refreshed segments need scores. The scoring job can take a while on larger refreshes; Railway logs show progress output such as `Scored 200/8442 segments`.

To check scoring progress from the CLI:

```bash
railway logs --latest -s walkmap -n 320
```

### Manual verification

- `curl https://<railway-url>/health` returns `{"status":"ok"}`.
- `curl "https://<railway-url>/segments?bbox=-74.09,40.69,-74.02,40.74"` returns Jersey City segment data.
- Railway logs show the batch scorer progressing and eventually finishing after `POST /admin/score/batch`.
- Railway deploy logs show `alembic upgrade head` completing before the app starts.
