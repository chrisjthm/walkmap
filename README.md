# Walkmap

Walkmap is a web app for planning urban walks and runs optimized for route experience, not just speed. The MVP stack includes:

- `postgres`: PostgreSQL 16 + PostGIS
- `api`: FastAPI backend
- `frontend`: React + Vite frontend

## Local Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)

### 1. Configure environment

Create a local env file from the template:

```bash
cp .env.example .env
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

### 4. Stop services

```bash
docker compose down
```

To also remove volumes:

```bash
docker compose down -v
```

## Development Notes

- API hot reload is enabled via `uvicorn --reload`.
- Frontend hot reload is enabled by Vite.
- Postgres data persists in the `postgres_data` Docker volume across restarts.
- If `.env` is missing or required variables are unset, Compose fails fast with a clear error.
