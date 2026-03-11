# Aesthetic Walk & Run Planner — Technical Implementation Tasks

**Version:** 0.1  
**Companion to:** Product Specification v0.1

---

## How to Read This Document

Each task includes:
- **Description** — what needs to be built and key design notes
- **Completion criteria** — observable, testable definition of done
- **Test cases** — specific scenarios to verify
- **Stream** — which parallel work stream this belongs to

### Work Streams

Tasks are organized into parallel streams that can be executed concurrently by independent developers (or sequentially by a solo developer in the order listed within each stream). Dependencies between streams are called out explicitly.

| Stream | Label | Focus |
|---|---|---|
| A | `[A]` | Infrastructure & DevOps |
| B | `[B]` | Data Ingest & AI Scoring |
| C | `[C]` | Backend API |
| D | `[D]` | Routing Engine |
| E | `[E]` | Frontend |

**Dependency summary:**
- Stream B depends on A (needs the database)
- Stream C depends on A (needs the database); can begin with stubbed responses before B completes
- Stream D depends on B (needs scored segments in DB); can be developed against mock scored data in parallel
- Stream E can begin immediately with mocked API responses; integrates fully once C and D are complete

```
A ──► B ──► D ──┐
A ──► C ─────────┼──► Integration Milestones
E (mock) ───────┘
```

---

## Stream A — Infrastructure & DevOps

### A1 — Docker Compose Local Environment

**Description:**
Set up a Docker Compose configuration that spins up all local development dependencies with a single `docker compose up` command. This is the foundation every other stream depends on.

Services required:
- `postgres`: PostgreSQL 16 with PostGIS extension enabled
- `api`: FastAPI app (hot-reload via `uvicorn --reload`)
- `frontend`: React dev server (Vite)

Include a `.env.example` file documenting all required environment variables (DB connection string, JWT secret, Mapbox token).

**Completion criteria:**
- `docker compose up` starts all three services without errors
- PostgreSQL is reachable at `localhost:5432` with PostGIS available (`SELECT PostGIS_Version()` returns a result)
- FastAPI health check endpoint `GET /health` returns `{"status": "ok"}`
- Frontend dev server is reachable at `localhost:5173`
- Hot reload works: editing a `.py` file restarts the API; editing a `.tsx` file updates the browser

**Test cases:**
1. Fresh checkout → `docker compose up` → all services healthy within 60 seconds
2. `docker compose down && docker compose up` → state persists in Postgres (volume mount confirmed)
3. Kill the API container → `docker compose up api` restarts it without affecting Postgres
4. Missing `.env` file → startup fails with a clear error message, not a silent crash

---

### A2 — Database Schema & Migrations

**Description:**
Define the full PostgreSQL schema using Alembic for migrations. All geospatial columns must use PostGIS types. Schema must match the data model in spec Section 6.2.

Tables:
- `users` — id (uuid PK), email (unique), password_hash, created_at
- `segments` — id (text PK, OSM-derived), geometry (PostGIS `GEOMETRY(LineString, 4326)`), osm_tags (jsonb), ai_score (float), ai_confidence (float), user_score (float nullable), composite_score (float), verified (boolean default false), rating_count (int default 0), vibe_tag_counts (jsonb default `{}`), last_updated (timestamptz)
- `ratings` — id (uuid PK), segment_id (FK → segments), user_id (FK → users), thumbs_up (boolean), vibe_tags (text[]), created_at (timestamptz), unique constraint on (segment_id, user_id)
- `routes` — id (uuid PK), user_id (FK → users), start_point (PostGIS `GEOMETRY(Point, 4326)`), end_point (PostGIS `GEOMETRY(Point, 4326)` nullable), mode (enum: loop/point-to-point/point-to-destination), priority (enum: highest-rated/dining/residential/explore), segment_ids (text[]), distance_m (float), duration_s (int), avg_score (float), created_at (timestamptz)

Indexes required:
- `segments.geometry` — PostGIS GIST index (spatial queries)
- `segments.composite_score` — B-tree (sorting/filtering by score)
- `ratings.segment_id` — B-tree (aggregation per segment)
- `ratings.user_id` — B-tree (user history queries)

**Completion criteria:**
- `alembic upgrade head` runs cleanly on a fresh database
- `alembic downgrade base` cleanly removes all tables
- All PostGIS types correctly created (verify with `\d segments` in psql)
- All indexes exist (verify with `\di`)
- Unique constraint on `ratings(segment_id, user_id)` enforced at DB level

**Test cases:**
1. `alembic upgrade head` on empty DB → all tables and indexes created, no errors
2. Insert a test segment with a LineString geometry → `ST_AsText(geometry)` returns correct WKT
3. Insert a rating → FK constraint enforced (inserting with non-existent segment_id raises error)
4. Insert two ratings for the same (segment_id, user_id) pair → unique constraint violation raised
5. `alembic downgrade base` → all tables dropped cleanly
6. `alembic upgrade head` a second time → idempotent, no errors

---

### A3 — CI Pipeline

**Description:**
Set up a GitHub Actions workflow that runs on every pull request and push to `main`.

Jobs:
- `test-backend`: spins up a Postgres service container with PostGIS, runs `pytest` against the full test suite
- `test-frontend`: runs `vitest` unit tests and TypeScript type check (`tsc --noEmit`)
- `lint`: runs `ruff` (Python) and `eslint` (TypeScript)

**Completion criteria:**
- Pipeline runs automatically on every push and pull request
- A failing test causes the pipeline to fail and blocks merge
- Pipeline completes in under 3 minutes for the MVP codebase size
- All three jobs run in parallel

**Test cases:**
1. Push a branch with a deliberate failing pytest test → pipeline fails, reports the correct test name
2. Fix the test, push again → pipeline passes
3. Introduce a TypeScript type error → `tsc` step fails with the correct file/line reported
4. All three jobs shown running concurrently in the GitHub Actions UI

---

## Stream B — Data Ingest & AI Scoring

*Depends on: A1, A2*

### B1 — OSM Data Ingest Pipeline

**Description:**
Build a Python script (runnable as a CLI command and as a FastAPI background task) that fetches all pedestrian-navigable street segments within a bounding box using OSMnx, decomposes them into individual node-to-node segments, and stores them in the `segments` table.

Jersey City MVP bounding box: `north=40.7282, south=40.7080, east=-74.0150, west=-74.0600`

Key implementation notes:
- Use `osmnx.graph_from_bbox()` with `network_type="walk"` to get the pedestrian graph
- Each graph edge (u, v, key) becomes one segment; use a stable string ID derived from these values
- Store the full OSM tags dict in the `osm_tags` jsonb column
- Store edge geometry as a PostGIS LineString (OSMnx provides this via `ox.graph_to_gdfs()`)
- Script must be idempotent: re-running upserts without duplicating rows
- Abstract the data fetch behind a `DataProvider` interface so the OSM source can be swapped later

**Completion criteria:**
- Ingest script completes for the Jersey City bounding box without errors
- All pedestrian segments within the bounding box are stored in `segments`
- Geometry is a valid PostGIS LineString in WGS84 (SRID 4326)
- Re-running the script is fully idempotent (row count does not increase on second run)
- `ai_score` and `ai_confidence` are NULL after ingest (scoring is a separate step, B3)

**Test cases:**
1. Run ingest → `SELECT COUNT(*) FROM segments` returns > 500 rows
2. `SELECT COUNT(*) FROM segments WHERE ST_IsValid(geometry) = false` → 0 rows
3. `SELECT COUNT(*) FROM segments WHERE osm_tags IS NULL` → 0 rows
4. Run ingest twice → row count identical on both runs
5. Sample 10 random segments, verify their geometries fall within the Jersey City bounding box via `ST_Within`
6. `SELECT COUNT(*) FROM segments WHERE ai_score IS NOT NULL` → 0 rows immediately after ingest (before scoring)

---

### B2 — AI Scoring Engine

**Description:**
Implement the scoring function defined in spec Section 7. This is a pure Python function — no external API calls, no database access. It operates entirely on data passed in as arguments.

Function signature:
```python
def score_segment(
    osm_tags: dict,
    nearby_pois: list[dict],   # OSM POI tag dicts for features within 50m
    factor_weights: dict       # loaded from scoring_config.yml
) -> ScoringResult:            # { score: float, confidence: float, factors: dict }
```

Factor weights must live in a `scoring_config.yml` file — never hardcoded in the function.

Factors to implement (all 13 from spec Section 7.2): road type (positive and negative), sidewalk presence, surface quality, tree cover proxy, waterfront proximity, business density, park adjacency, industrial land use, residential land use, speed limit proxy.

Also implement `update_composite_score()` which applies the blending formula from spec Section 7.3.

**Completion criteria:**
- All 13 factors from spec Section 7.2 are implemented and covered by unit tests
- Factor weights are loaded from `scoring_config.yml`, not hardcoded
- Highways (`highway=motorway/trunk/primary`) always produce score < 30
- Waterfront footpaths produce score > 70
- Residential streets with sidewalks produce score > 55
- `confidence` is between 0.0 and 1.0 for all inputs
- Segments with fewer than 3 OSM tags produce confidence < 0.4
- `update_composite_score()` correctly implements the three-case blending formula from spec Section 7.3

**Test cases:**
1. `score_segment({"highway": "motorway"}, [], weights)` → score < 30
2. `score_segment({"highway": "footway", "sidewalk": "both"}, [{"natural": "water"}], weights)` → score > 70
3. `score_segment({"highway": "residential", "sidewalk": "both"}, [5 restaurant POIs], weights)` → score > 55
4. `score_segment({"highway": "residential"}, [], weights)` (only 1 tag) → confidence < 0.4
5. `update_composite_score(ai_score=60, user_ratings=[], ...)` → composite=60, verified=False
6. `update_composite_score(ai_score=60, user_ratings=[True, True, True], ...)` → composite is blend, verified=True
7. `update_composite_score(ai_score=60, user_ratings=[True]*6, ...)` → composite ≈ 100, ai weight negligible
8. Modify a weight in `scoring_config.yml`, re-run same input → output score changes accordingly

---

### B3 — Batch Scoring Runner

**Description:**
Build a CLI script and FastAPI background task that:
1. Fetches all unscored segments from the DB (`ai_score IS NULL`)
2. For each segment, fetches nearby POIs using a PostGIS spatial query (`ST_DWithin` with 50m radius)
3. Calls the scoring function from B2
4. Writes `ai_score`, `ai_confidence`, `composite_score`, and `last_updated` back to the DB in bulk

Must handle interruption gracefully — can be stopped and resumed without reprocessing already-scored segments. Progress should be logged to stdout (e.g. "Scored 250/3000 segments").

**Completion criteria:**
- After a full run, `SELECT COUNT(*) FROM segments WHERE ai_score IS NULL` returns 0
- Score distribution is broad — not collapsed to a narrow band
- Resuming after interruption skips already-scored segments (unless `--force` flag is passed)
- Full Jersey City dataset completes in under 5 minutes

**Test cases:**
1. Run batch scorer on fully unscored DB → 0 unscored segments remain
2. `SELECT MIN(ai_score), MAX(ai_score), AVG(ai_score) FROM segments` → min < 20, max > 75, avg between 40–65
3. Run scorer, interrupt at ~50%, resume → completes without reprocessing already-scored segments
4. Run `--force` flag → all segments rescored, `last_updated` timestamps refreshed
5. Manual spot-check: the Hudson River waterfront path segments score > 70; a segment adjacent to the NJ Turnpike scores < 30

---

## Stream C — Backend API

*Depends on: A1, A2. Can begin with stubbed/mock responses before B completes.*

### C1 — Auth Endpoints

**Description:**
Implement email/password authentication using bcrypt for password hashing and PyJWT for token issuance.

Endpoints:
- `POST /auth/register` — creates a new user, returns JWT
- `POST /auth/login` — validates credentials, returns JWT
- `GET /auth/me` — returns current user info (requires valid JWT)

JWT should be 24-hour expiry. A `get_current_user` FastAPI dependency must be implemented and reusable across all protected endpoints.

**Completion criteria:**
- Registration with a duplicate email returns 409
- Login with wrong password returns 401
- All protected endpoints return 401 without a valid JWT
- Passwords are never stored or returned in plaintext
- JWT payload contains `user_id` and `exp` claims

**Test cases:**
1. `POST /auth/register` with valid email/password → 201, JWT returned
2. `POST /auth/register` same email again → 409
3. `POST /auth/login` with correct credentials → 200, JWT returned
4. `POST /auth/login` with wrong password → 401
5. `GET /auth/me` with valid JWT → 200, returns `email` and `id`
6. `GET /auth/me` with expired/malformed JWT → 401
7. `SELECT password_hash FROM users` — value is a bcrypt hash (starts with `$2b$`), never plaintext

---

### C2 — Segments API

**Description:**
Endpoints for fetching segment data to power the map overlay and detail panel.

Endpoints:
- `GET /segments?bbox={west},{south},{east},{north}` — returns all segments within the bounding box as a GeoJSON FeatureCollection
- `GET /segments/{segment_id}` — returns full detail for a single segment

The bbox endpoint must use PostGIS `ST_Intersects` for spatial filtering. Each GeoJSON feature must include: `segment_id`, `composite_score`, `verified`, `rating_count`, `vibe_tag_counts`.

**Completion criteria:**
- Returns valid GeoJSON FeatureCollection for all bbox queries
- Only segments intersecting the bbox are returned
- `GET /segments/{id}` returns full detail including `ai_score`, `ai_confidence`, `osm_tags`
- Full Jersey City bbox query completes in under 500ms (spatial index must be in use)

**Test cases:**
1. Query bbox covering a known waterfront block → that segment appears in response
2. Query bbox over open water (no segments) → empty FeatureCollection, not an error
3. All returned geometries fall within the queried bbox (verified with `ST_Within`)
4. `GET /segments/{valid_id}` → 200 with all required fields
5. `GET /segments/{nonexistent_id}` → 404
6. Response is valid GeoJSON (validate against GeoJSON spec)
7. Full Jersey City bbox (`EXPLAIN ANALYZE`) confirms GIST index is used, query < 500ms

---

### C3 — Ratings API

**Description:**
Endpoints for submitting and retrieving segment ratings. All write operations require authentication.

Endpoints:
- `POST /ratings` — submit or update a rating (thumbs up/down + optional vibe tags)
- `GET /segments/{segment_id}/ratings` — list ratings for a segment
- `GET /users/me/ratings` — current user's rating history

On `POST /ratings`, the following must happen atomically in a single transaction:
1. Upsert the rating row (insert or update if user already rated this segment)
2. Recalculate `user_score` as a smoothed thumbs-up percentage
3. Recalculate `composite_score` using the blending formula (spec Section 7.3)
4. Update `verified`, `rating_count`, and `vibe_tag_counts` on the segment

**Completion criteria:**
- Submitting a rating immediately updates the segment's `composite_score` and is reflected in subsequent `GET /segments` responses
- A user submitting a second rating for the same segment updates rather than duplicates
- `vibe_tag_counts` correctly aggregates all tags across all ratings for a segment
- Unauthenticated `POST /ratings` returns 401
- Score recalculation is atomic — no partial state if the transaction fails

**Test cases:**
1. Submit thumbs-up for an unverified segment → `verified=true`, `rating_count=1` on subsequent GET
2. Submit 5 consecutive thumbs-up ratings (from 5 users) → `composite_score` converges toward 100
3. Same user rates segment thumbs-up then thumbs-down → `rating_count` remains 1, score reflects the update
4. Submit rating with `vibe_tags=["scenic", "waterfront"]` → both appear in `vibe_tag_counts` with count 1
5. `POST /ratings` without Authorization header → 401
6. `GET /segments/{id}/ratings` → returns list with correct `thumbs_up` and `vibe_tags` per rating
7. Simulate a DB error mid-transaction → neither the rating row nor the segment update is persisted

---

### C4 — Routes API

**Description:**
Endpoint that accepts route planning parameters, delegates to the routing engine (Stream D), and returns 2–3 suggested routes.

Endpoints:
- `POST /routes/suggest` — returns route candidates (no auth required)
- `POST /routes` — saves a selected route to history (auth required)
- `GET /users/me/routes` — returns saved route history (auth required)

Request body for `POST /routes/suggest`:
```json
{
  "start": { "lat": 40.7178, "lng": -74.0431 },
  "end": { "lat": 40.7200, "lng": -74.0400 },
  "mode": "loop",
  "distance_m": 3000,
  "activity": "walk",
  "priority": "highest-rated"
}
```

Each returned route must include: ordered list of segment IDs, GeoJSON LineString geometry, `distance_m`, `duration_s`, `avg_score`, `verified_count`, `unverified_count`.

**Completion criteria:**
- Returns 2–3 routes with Jaccard similarity < 0.5 between any pair
- Each route's distance is within ±15% of requested `distance_m`
- Response time < 3 seconds for a 5km loop in Jersey City
- Routes only traverse pedestrian-navigable segments
- `POST /routes/suggest` works without authentication

**Test cases:**
1. Request 3km loop from waterfront → 2–3 routes returned, all approximately 3km (±450m)
2. All segment IDs in response exist in the `segments` table
3. Any two returned routes have Jaccard similarity < 0.5 on their segment ID sets
4. `priority=dining` routes pass more restaurant-adjacent segments than `priority=residential` routes (same O/D)
5. Point-to-destination request → route ends within 100m of specified destination
6. Request with `distance_m=80000` (unreachable for Jersey City) → graceful error with descriptive message
7. Response GeoJSON geometries are valid and form a continuous path (no gaps)

---

## Stream D — Routing Engine

*Depends on: B1 (graph structure), B2/B3 (segment scores). Can be prototyped against mock scored data.*

### D1 — Pedestrian Graph Construction

**Description:**
Build and cache an in-memory NetworkX directed graph from the `segments` table. This graph is the foundation for all routing.

Graph structure:
- Nodes: OSM node IDs with lat/lng attributes
- Edges: one per segment, with attributes: `segment_id`, `distance_m`, `composite_score`, `verified`, `osm_tags` snapshot, precomputed priority mode flags (e.g. `near_restaurant: bool`, `is_residential: bool`)
- Edge weight: `1.0 - (composite_score / 100.0)` (low score = high cost)

The graph is built at API startup and cached. Provide a `refresh_graph()` function that rebuilds from the DB — called after bulk score updates (B3) or when triggered by a background task.

**Completion criteria:**
- Graph builds from DB in under 10 seconds for the Jersey City dataset
- `len(G.edges())` > 500 after build
- Edge weights correctly reflect composite scores (waterfront segment has lower weight than highway-adjacent segment)
- `refresh_graph()` picks up score changes made after the initial build
- Disconnected components are identified and logged (graph may not be fully connected)

**Test cases:**
1. Build graph → `len(G.edges())` > 500, `len(G.nodes())` > 300
2. A known high-score segment (waterfront) has lower edge weight than a known low-score segment (highway service road)
3. All edge `segment_id` values resolve to rows in the `segments` table
4. Update a segment's `composite_score` in DB, call `refresh_graph()` → edge weight updated accordingly
5. Log output from graph build includes component count if graph is not fully connected

---

### D2 — Point-to-Point and Point-to-Destination Routing

**Description:**
Score-optimized routing between two points using NetworkX's A* algorithm on the pedestrian graph.

The implementation must:
- Snap input lat/lng to the nearest graph node (using OSMnx `nearest_nodes` or equivalent)
- Find the lowest-weight (highest-score) path from origin to destination
- Apply priority mode weight modifiers per spec Section 8.2
- Generate 2–3 candidates with low segment overlap using directional penalization or small random weight perturbation

**Completion criteria:**
- Returns a valid connected path for any two reachable points within the Jersey City bounding box
- Path uses only pedestrian edges (no `highway=motorway/trunk/primary` edges)
- `priority=dining` routes have higher average proximity to restaurants than `priority=residential` routes on the same O/D pair
- Two routes returned for the same O/D pair have Jaccard similarity < 0.5

**Test cases:**
1. Route from Newport PATH station (40.7271, -74.0332) to Hamilton Park (40.7195, -74.0483) → valid path, all edges pedestrian-navigable
2. Same O/D with `priority=highest-rated` vs `priority=residential` → routes differ, average scores differ by > 10 points
3. Origin = destination → returns empty route or graceful error (not a crash)
4. Ocean coordinate as origin → snaps to nearest valid land node without error
5. Two routes for same O/D → Jaccard similarity on segment ID sets < 0.5

---

### D3 — Loop Routing

**Description:**
Generate loop routes that start and end at the same node and cover approximately a target distance, maximizing aesthetic score.

Approach: randomized greedy expansion from origin — repeatedly extend along the highest-scoring unvisited edge that keeps the remaining distance budget feasible, then close the loop back to origin via shortest path. Generate 2–3 candidates by seeding expansion in different compass quadrant directions (N, E, S, W bias).

**Completion criteria:**
- All returned routes start and end at the same graph node
- Total distance within ±15% of the requested target
- No segment appears more than once in a single route
- 2–3 candidates returned with pairwise Jaccard similarity < 0.5

**Test cases:**
1. Request 2km loop from Grove Street PATH → start node = end node, confirmed
2. Actual route distance within ±300m of 2000m
3. No repeated segment IDs in a single returned route
4. 2–3 routes returned for a 1km loop request, pairwise Jaccard < 0.5
5. Request 10km loop in the small Jersey City bounding box → returns best-effort route with a descriptive note if full distance is unachievable; does not crash

---

### D4 — Explore Mode Routing

**Description:**
A routing variant that prioritizes unverified segments with high AI confidence, used in Explore mode (spec Section 5.5).

Weight modification: rather than minimizing `1 - score`, minimize `verified_penalty + low_confidence_penalty`. Specifically:
- Verified segments: standard weight
- Unverified segments with `ai_confidence > 0.6`: weight reduced by 40% (strongly preferred)
- Unverified segments with `ai_confidence <= 0.6`: standard weight (not actively penalized)
- Segments with `ai_score < 20`: excluded from the graph for this mode (hard filter)

Preference for segments adjacent to already-verified high-scoring segments is implemented by applying a mild bonus to edges that share a node with a verified segment.

**Completion criteria:**
- Explore mode routes contain a higher fraction of unverified segments than equivalent `highest-rated` routes from the same origin
- No segment with `ai_score < 20` appears in any explore route (unless no walkable alternative exists)
- Routes are still valid loops or paths within the ±15% distance tolerance
- Fractions are measurably different: explore routes should be at least 20% more unverified segments than highest-rated routes

**Test cases:**
1. Generate a 3km explore loop and a 3km highest-rated loop from same origin → explore loop has ≥ 20% more unverified segments by count
2. No segment in explore route has `ai_score < 20` (query the DB to verify)
3. Explore loop is a valid loop (start node = end node, distance within ±15%)
4. Explore route has at least some segments adjacent to known high-score verified segments (confirming the adjacency bonus is working)

---

## Stream E — Frontend

*Can begin immediately with mocked API responses. Full integration requires C2, C3, C4.*

### E1 — Project Setup & Base Layout

**Description:**
Initialize the React + TypeScript frontend with Vite. Configure Tailwind CSS, React Query, and React Router. Establish the base layout: a full-screen map area with a collapsible side panel. The map provider for E2 is MapLibre GL JS with OpenFreeMap styles (no Mapbox token required).

Routes:
- `/` — map view (default)
- `/plan` — route planner panel open
- `/explore` — explore mode panel open
- `/login` and `/register` — auth screens

**Completion criteria:**
- `npm run dev` starts without errors
- `npm run typecheck` (`tsc --noEmit`) passes with zero errors in strict mode
- Tailwind classes apply correctly in the browser
- Base layout renders: full-screen map area + side panel visible on `/plan`

**Test cases:**
1. `npm run dev` → loads at localhost:5173 with no console errors
2. `npm run typecheck` → zero TypeScript errors
3. Navigate to `/plan` → side panel renders (can be a placeholder component for now)
4. Navigate to `/explore` → explore panel renders
5. Side panel is collapsible: clicking a toggle hides/shows it without breaking the map layout

---

### E2 — Map View & Aesthetic Overlay

**Description:**
Implement the map view using MapLibre GL JS with OpenFreeMap styles/tiles. Street segments are rendered as a colored line layer sourced from `GET /segments?bbox=...`.

Implementation notes:
- Fetch segments on map load and on `moveend` event (debounced 300ms)
- Render as a MapLibre GeoJSON source + `line` layer
- Base map style URL should use OpenFreeMap (e.g. `https://tiles.openfreemap.org/styles/liberty` or another approved OpenFreeMap style)
- Color expression: MapLibre `interpolate` expression mapping score 0–100 to the gradient in spec Section 4.3
- Unverified segments: `line-dasharray: [2, 2]`
- Verified segments: solid line
- Clicking a segment: opens a detail panel showing name, score, verification badge, vibe tag counts, rating count
- Toggle: show/hide overlay; show verified-only

**Completion criteria:**
- All segments in the current viewport render with the correct gradient color
- Unverified segments visually distinct (dashed)
- Segment click opens detail panel with correct data pulled from `GET /segments/{id}`
- Overlay re-fetches on pan/zoom with debounce
- Toggle buttons correctly show/hide overlay and filter to verified-only

**Test cases:**
1. Load app over Jersey City waterfront → OpenFreeMap basemap renders and colored segment lines visible
2. A segment with score 85 renders deep green; a segment with score 15 renders red
3. An unverified segment renders with a dashed line; a verified segment renders solid
4. Click a segment → detail panel appears with `segment_id`, score, `verified` badge, vibe tags
5. Toggle overlay off → all colored lines disappear; toggle on → reappear
6. Pan map 500m → new segments load in the new viewport (confirmed via Network tab)

---

### E3 — Route Planner UI

**Description:**
Build the route planning side panel. User configures parameters and receives 2–3 route suggestions rendered on the map.

UI components:
- Start location input (text search + "Use my location" button)
- End location input (shown only when mode is point-to-destination)
- Route mode selector: Loop / Point-to-point / Point-to-destination
- Distance slider (0.5–15 miles) or duration slider (15 min – 3 hrs), with a toggle between the two
- Activity selector: Walk / Run (affects speed estimate for duration display)
- Priority mode selector: Highest Rated / Dining & Shopping / Residential / Explore
- "Find Routes" button with loading state
- Results: 2–3 route cards (distance, estimated time, avg score badge, verified/unverified count)
- Clicking a route card highlights that route on the map in a distinct color; others de-emphasize

**Completion criteria:**
- All form inputs produce a correct `POST /routes/suggest` request body
- Loading spinner shown during API call
- 2–3 routes rendered on map in distinct colors when results arrive
- Selecting a route card highlights it and dims others
- Error state shown if API returns an error (not a crash or blank screen)

**Test cases:**
1. Fill all fields, click "Find Routes" → loading spinner appears, then 2–3 routes render on map
2. Routes render in visually distinct colors (e.g. blue, orange, purple)
3. Click route card 1 → highlighted on map; click route card 2 → card 2 highlighted, card 1 de-emphasized
4. "Use my location" → browser geolocation API triggered, coordinates populate start field
5. Mock API returning a 500 error → user sees a friendly error message, not a blank panel
6. Distance slider at 1 mile → route cards show approximately 1 mile; at 5 miles → approximately 5 miles

---

### E4 — Rating UI

**Description:**
Build the segment rating interaction: tapping a segment opens a detail/rating panel; user submits thumbs up/down and optional vibe tags.

Components:
- Segment detail panel: street name, composite score, verification badge, existing vibe tag counts (ranked by frequency), rating count
- Rating interaction: thumbs up / thumbs down (toggle, one active at a time)
- Vibe tag picker: chip grid of suggested tags (spec Section 5.3.1), multi-selectable
- Submit button → calls `POST /ratings`, shows success toast, closes panel
- If user already rated this segment: pre-populate their previous rating and tags
- Post-walk rating prompt (spec Section 5.4): after a route is saved, surface 3–5 unrated segments from that route for sequential quick rating

**Completion criteria:**
- Tapping a segment opens the panel with correct data
- Thumbs up/down shows clear selected/unselected state
- Vibe tags are multi-selectable; deselecting a tag removes it from the pending submission
- Submitting a rating calls `POST /ratings` with the correct payload and triggers a segment data refresh (map color updates)
- If user previously rated the segment, their previous choice is pre-selected on open
- Post-walk prompt surfaces segments in priority order: unverified segments first

**Test cases:**
1. Click segment → detail panel opens with correct name, score, and rating count
2. Click thumbs up → button shows active/selected state; click thumbs down → thumbs down active, thumbs up deactivated
3. Select "Scenic" and "Waterfront" → both chips highlighted; deselect "Scenic" → only "Waterfront" highlighted
4. Click Submit (authenticated) → `POST /ratings` called with correct body; success toast shown
5. After submission, segment color on map updates to reflect new composite score (no page reload required)
6. Click same segment again → previous thumbs-up pre-selected in the panel
7. Save a route with 10 segments → post-walk prompt shows the 3–5 unrated segments from that route

---

### E5 — Auth UI

**Description:**
Login and registration screens. Redirect unauthenticated users to `/login` when they attempt to rate or save a route. Store the JWT in React context (not localStorage or sessionStorage) and attach it to all API requests via an interceptor.

**Completion criteria:**
- Register and login forms validate inputs client-side before submitting
- JWT stored in React context / in-memory only (explicitly not in localStorage)
- All authenticated API calls include `Authorization: Bearer <token>` header
- Unauthenticated access to a protected action redirects to `/login`, then back after successful login
- Logging out clears the token from context and redirects to `/login`

**Test cases:**
1. Register with valid email/password → redirected to map, user info shown in UI
2. Register with invalid email format → client-side validation error before API call is made
3. Attempt to submit a rating while logged out → redirected to `/login`; after login, returned to map
4. Refresh the page → user is logged out (JWT is not persisted — this is correct MVP behavior)
5. Log out → subsequent `GET /auth/me` call returns 401 (token no longer attached to requests)
6. Login with wrong password → server 401 shown as a user-facing error message in the form

---

## Cross-Stream Integration Milestones

These are not implementation tasks but observable checkpoints confirming streams are integrating correctly.

### M1 — Scored Map *(A + B + E2 complete)*

**Verify:** Load the app centered on the Jersey City waterfront. The Hudson River promenade segments appear deep green. A segment running under or alongside the NJ Turnpike appears red or orange. Unverified segments render as dashed lines.

---

### M2 — End-to-End Route *(C4 + D + E3 complete)*

**Verify:** Enter a start point near Grove Street PATH station. Request a 2km loop with "Highest Rated" priority. Two or three distinct colored routes appear on the map. Each route card shows a plausible distance (~2km) and an average aesthetic score.

---

### M3 — Rating Loop *(C3 + E4 complete)*

**Verify:** Click a dashed (unverified) segment near the waterfront. Rate it thumbs-up with tags "Scenic" and "Waterfront". The segment's line changes from dashed to solid and its color updates to reflect the new composite score. Reload the app — the score and tags persist.

---

### M4 — Full Personal Beta Walk *(all streams complete)*

**Verify:** Use the app on a mobile browser (responsive web) to plan a 30-minute walk from the Jersey City waterfront. Follow one of the suggested routes. After the walk, use the post-walk rating prompt to rate 3–5 segments encountered. Confirm all ratings persisted, composite scores updated, and previously-dashed segments are now shown as solid.
