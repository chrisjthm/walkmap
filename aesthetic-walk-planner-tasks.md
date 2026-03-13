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

### B1.1 — Ingest: Pedestrian-First Segment Filtering

**Description:**
Reverts and replaces the sidewalk suppression logic from C2.2. Rather than suppressing parallel footway segments at the API layer, apply correct inclusion/exclusion rules at ingest time so the dataset only contains segments relevant to a pedestrian walk planner. Roads are largely noise on a walk map — the core dataset should be the pedestrian network, with road carriageways included only as a fallback where no better walking surface exists.

Remove the C2.2 suppression logic from the segments API entirely once this task is complete.

**Inclusion rules (apply during OSM ingest in B1):**

| Highway type | Rule | Notes |
|---|---|---|
| `footway`, `path`, `pedestrian`, `steps` | Always include | Core pedestrian network |
| `living_street` | Always include | Pedestrian-priority shared space |
| `residential` (low speed / low traffic) | Include | Legitimate walking surface |
| `residential` or `tertiary` with no parallel mapped sidewalk | Include, score penalty | Fallback only — apply -15 to ai_score |
| `secondary` with `sidewalk=both/left/right` | Include | Sidewalk mapped as attribute, not separate way |
| `secondary` or `tertiary` with no sidewalk tag | Exclude | If sidewalk exists as separate way, carriageway is redundant; if it doesn't, not a good walking surface |
| `motorway`, `trunk`, `primary` | Always exclude | Never appropriate for pedestrians |
| `service`, `track` | Exclude | Too ambiguous; waterfront proximity scoring will catch legitimate exceptions |

**Completion criteria:**
- Re-ingested dataset contains no `motorway`, `trunk`, or `primary` segments
- Re-ingested dataset contains no `secondary` or `tertiary` segments without a sidewalk tag
- Footway, path, and pedestrian segments are all retained
- C2.2 suppression logic is removed from the segments API
- Segment count after re-ingest is plausible (expect a reduction in total segments but an increase in the ratio of pedestrian-specific ways)

**Test cases:**
1. `SELECT COUNT(*) FROM segments WHERE osm_tags->>'highway' IN ('motorway', 'trunk', 'primary')` → 0 rows after re-ingest
2. `SELECT COUNT(*) FROM segments WHERE osm_tags->>'highway' IN ('secondary', 'tertiary') AND osm_tags->>'sidewalk' IS NULL` → 0 rows
3. `SELECT COUNT(*) FROM segments WHERE osm_tags->>'highway' = 'footway'` → significantly more rows than carriageway types, confirming pedestrian ways dominate the dataset
4. Visual check: the map overlay shows footpaths, park paths, and sidewalks prominently; road carriageways are largely absent except quiet residential streets
5. Mary Benson Park paths and Hudson River promenade paths are present and rendering correctly
6. `GET /segments?bbox=...` response no longer applies any suppression logic — all included segments are returned as-is

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

### B2.1 — Scoring: Waterfront Proximity Gradient

**Description:**
Replace the binary waterfront proximity check with a distance-band gradient. Query `ST_Distance` from the segment midpoint to the nearest `natural=water`, `waterway=*`, or `leisure=marina` feature in the OSM data. Apply a tiered bonus:

| Distance to water | Score bonus |
|---|---|
| 0–40m | +25 |
| 41–80m | +10 |
| 81–150m | +4 |
| > 150m | 0 |

The Hudson River promenade in Jersey City should be the clearest beneficiary — segments directly on the waterfront path should score noticeably higher than inland streets.

**Completion criteria:**
- Three distinct score tiers are visible on the map along the waterfront → inland gradient
- The Hudson River promenade segments score > 75
- Segments 2+ blocks inland from the waterfront receive no waterfront bonus

**Test cases:**
1. Score a mock segment with midpoint 30m from water → bonus of +25 applied
2. Score a mock segment 60m from water → bonus of +10 applied
3. Score a mock segment 120m from water → bonus of +4 applied
4. Score a mock segment 200m from water → no bonus
5. After re-running B3, verify in DB: `SELECT AVG(ai_score) FROM segments WHERE ST_DWithin(geometry, <hudson_river_geom>, 40)` is > 75
6. Visual check: waterfront promenade is clearly greener than one block inland on the map

---

### B2.2 — Scoring: POI Density Gradient

**Description:**
Replace the flat POI proximity bonus with a tiered count-based score. Count OSM POIs (restaurants, cafes, bars, shops, amenities) within 50m of the segment midpoint and apply progressive bonuses:

| POI count within 50m | Score bonus |
|---|---|
| 0 | 0 |
| 1–3 | +8 |
| 4–8 | +16 |
| 9+ | +22 |

Cap the bonus at +22 to avoid over-rewarding extremely dense commercial corridors at the expense of all other factors.

**Completion criteria:**
- Grove Street and Newark Avenue (dense commercial) score measurably higher than adjacent residential blocks
- The bonus never exceeds +22 regardless of POI count
- Purely residential blocks with 0 POIs receive no POI bonus

**Test cases:**
1. `score_segment(..., nearby_pois=[])` → POI bonus = 0
2. `score_segment(..., nearby_pois=[p1, p2])` → POI bonus = +8
3. `score_segment(..., nearby_pois=[p1..p6])` → POI bonus = +16
4. `score_segment(..., nearby_pois=[p1..p15])` → POI bonus capped at +22
5. After re-running B3: Grove Street corridor segments average > 10 points higher than the nearest purely residential block

---

### B2.3 — Scoring: Residential Street Refinement

**Description:**
Currently all `highway=residential` segments score the same. Add sub-classification logic that penalizes residential streets with high-traffic characteristics:

- `oneway=yes` on a residential street → -8 (indicates higher vehicle throughput)
- `maxspeed > 25mph` (or `> 40kph`) → -10
- `lanes >= 2` → -8
- `highway=secondary` or `highway=tertiary` without sidewalk tags → -12
- `highway=living_street` (shared pedestrian/vehicle space) → +10 bonus

These modifiers stack but are capped: total penalty cannot exceed -20, total bonus cannot exceed +10 for this factor.

**Completion criteria:**
- A `highway=living_street` scores at least 10 points higher than an equivalent `highway=residential`
- A one-way residential street scores lower than an otherwise identical two-way residential street
- Multi-lane secondary streets without sidewalks score below 40

**Test cases:**
1. `score_segment({"highway": "residential", "oneway": "yes"}, ...)` scores lower than `score_segment({"highway": "residential"}, ...)` by ~8 points
2. `score_segment({"highway": "living_street"}, ...)` scores > 10 points higher than equivalent `highway=residential`
3. `score_segment({"highway": "secondary", "lanes": "2"}, ...)` with no sidewalk tag → score < 40
4. Stack two penalties: `oneway=yes` + `maxspeed=45` → total penalty = -18 (not -20, since cap applies)
5. After re-running B3: standard deviation of `ai_score` across all segments > 15

---

### B2.4 — Scoring: Park Adjacency Distance Bands

**Description:**
Replace the binary park proximity check with a distance gradient using `ST_Distance` from the segment midpoint to the nearest `leisure=park`, `leisure=playground`, or `landuse=grass` polygon:

| Distance to park | Score bonus |
|---|---|
| 0–20m | +18 |
| 21–75m | +10 |
| 76–150m | +4 |
| > 150m | 0 |

**Completion criteria:**
- Segments bordering a park edge score noticeably higher than segments one block away from the same park
- Hamilton Park and Van Vorst Park perimeter segments score > 70

**Test cases:**
1. Mock segment midpoint 10m from a park polygon → bonus = +18
2. Mock segment midpoint 50m from a park → bonus = +10
3. Mock segment midpoint 120m from a park → bonus = +4
4. Mock segment midpoint 200m from a park → bonus = 0
5. After re-running B3: segments directly bordering Hamilton Park average > 70

---

### B2.5 — Scoring: Intersection Density

**Description:**
Use the pedestrian graph structure (already built in D1) to compute a pedestrian interest score based on block length. Shorter blocks with more intersections create more interesting, navigable walks. Derive this from the segment's `distance_m`:

| Segment length | Score modifier |
|---|---|
| < 60m (very short block) | +8 |
| 60–120m (short block) | +4 |
| 121–250m (typical block) | 0 |
| > 250m (long block) | -6 |
| > 400m (very long block, highway-like) | -12 |

`distance_m` is already available on every segment from the OSMnx ingest.

**Completion criteria:**
- Short blocks in the Downtown grid score higher than long blocks of equivalent road type
- Segments > 400m (likely highway ramps or arterials) receive a meaningful penalty
- Factor is applied correctly from `distance_m` already stored in the segment

**Test cases:**
1. `score_segment` with `distance_m=45` → modifier = +8
2. `score_segment` with `distance_m=90` → modifier = +4
3. `score_segment` with `distance_m=180` → modifier = 0
4. `score_segment` with `distance_m=300` → modifier = -6
5. `score_segment` with `distance_m=500` → modifier = -12

---

### B2.6 — Scoring: Calibration Pass

**Description:**
After implementing B2.1–B2.5, re-run the batch scorer (B3) and validate the score distribution against known Jersey City ground truth. Tune `scoring_config.yml` weights until the distribution meets the targets below. This is a manual calibration step — no new code, just config tuning and spot-checking via DB queries and the map.

Known ground truth anchors for Jersey City:

| Location | Expected score range |
|---|---|
| Hudson River Waterfront Promenade | 80–95 |
| Grove Street / Newark Ave commercial corridor | 70–85 |
| Hamilton Park / Van Vorst Park perimeter | 70–80 |
| Typical Downtown residential grid | 50–65 |
| Jersey Ave near Turnpike ramps | 20–35 |
| NJ Turnpike service roads | 10–25 |

**Completion criteria:**
- Score standard deviation across all segments > 15
- All six ground truth anchors fall within their expected ranges
- Score distribution histogram shows meaningful spread across 20–90
- No more than 30% of segments fall within any single 10-point band

**Test cases:**
1. `SELECT STDDEV(ai_score) FROM segments` → > 15
2. Spot-check each ground truth anchor in the DB against its expected range
3. `SELECT WIDTH_BUCKET(ai_score, 0, 100, 10) AS bucket, COUNT(*) FROM segments GROUP BY bucket ORDER BY bucket` — no single bucket contains > 30% of all segments
4. Visual map check: clear differentiation visible between the waterfront, commercial corridors, residential grid, and highway-adjacent streets

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

### C2.1 — Segments API: Street Name in Response

**Description:**
Update `GET /segments` and `GET /segments/{id}` to include a human-readable `display_name` field in each feature's GeoJSON properties. Extract from `osm_tags` in priority order:

1. `osm_tags->>'name'` (e.g. "Grove Street")
2. If null: derive a label from `osm_tags->>'highway'` (e.g. `residential` → "Residential street", `footway` → "Footway", `path` → "Path")
3. If both null: `"Unnamed segment"`

This fallback hierarchy must be applied server-side so the frontend never has to handle it.

**Completion criteria:**
- No segment in the API response has `display_name = "Unnamed segment"` for any named street in Downtown Jersey City
- All segments have a non-null, non-empty `display_name`
- Fallback hierarchy is applied in the API, not the frontend

**Test cases:**
1. Fetch Grove Street segment → `display_name = "Grove Street"`
2. Fetch an unnamed footpath → `display_name = "Footway"` (not "Unnamed segment")
3. Zero features in the Jersey City bbox response have `display_name = "Unnamed segment"`
4. `GET /segments/{id}` for a named segment → `display_name` present and correct

---

### C2.2 — Segments API: Sidewalk Deduplication in Map Response

**Description:**
OSM models mapped sidewalks as separate `highway=footway` ways running parallel to their parent carriageway, tagged with `footway=sidewalk` and sometimes `sidewalk:of=<parent street name>`. This causes the map overlay to render three parallel lines for any street with mapped sidewalks — the carriageway plus two footways — where visually only one line is needed.

Sidewalk segments must be retained in the database (they are valid pedestrian routing paths and carry useful scoring signals), but the map overlay API response should suppress them when their parent carriageway is present in the same viewport.

**Suppression logic (apply in order):**

1. If a segment has `osm_tags->>'footway' = 'sidewalk'`, it is a candidate for suppression
2. Check whether a parent carriageway segment exists in the response within 20m and running parallel (bearing difference < 20°)
3. If a parent exists: suppress the sidewalk segment from the response
4. If no parent carriageway is present (e.g. the street itself is outside the viewport): include the sidewalk segment and apply name inheritance (see below)

**Name inheritance for sidewalk segments:**

When a sidewalk segment is included in the response (i.e. not suppressed), resolve `display_name` in this order:
1. `osm_tags->>'sidewalk:of'` — direct OSM parent reference (e.g. "Morris Street")
2. `osm_tags->>'name'` — occasionally present on sidewalk ways
3. Name of the nearest carriageway segment within 20m (PostGIS `ST_Distance` lookup)
4. Fallback to `"Footway"` only if none of the above resolve

**Completion criteria:**
- Streets with mapped sidewalks render as a single line on the map overlay, not three
- Suppressed sidewalk segments remain in the `segments` table and are still used by the routing engine
- Sidewalk segments that appear (when parent is out of viewport) display the parent street name, not "Footway"
- Non-sidewalk footways (standalone paths, park paths, pedestrian plazas) are unaffected by this logic

**Test cases:**
1. Mock API response for a block of Morris Street with carriageway + two sidewalk segments → only one line renders on the map
2. Query the DB directly after the API call → all three segments still present in the `segments` table
3. Fetch a viewport where only the sidewalk segments are present (parent carriageway just outside bbox) → sidewalk segments appear with the parent street name, not "Footway"
4. A standalone park footpath with no `footway=sidewalk` tag → unaffected, renders normally with its own label
5. `GET /segments/{id}` for a suppressed sidewalk segment → still returns full detail (suppression is overlay-only, not a deletion)
6. Visual check: Morris Street, Wayne Street, and Erie Street in Downtown Jersey City each render as a single line rather than three parallel lines

---

### C2.3 — Segments API: In-Memory Segment Cache

**Description:**
Rather than querying PostGIS on every `GET /segments?bbox=...` request, preload the full segment dataset into memory at API startup and serve bbox requests from the in-memory cache. For the Jersey City MVP dataset (~3,000–5,000 segments, ~3–5MB), this eliminates per-request DB latency and removes the need for a minimum zoom threshold on the frontend.

**Cache structure:**
Load all segments from PostGIS as a GeoJSON FeatureCollection on startup and store it in a module-level cache object alongside a timestamp. The bbox endpoint filters the in-memory collection using a simple coordinate bounds check — no spatial index needed at this scale.

**Cache refresh:**
- Expose a `refresh_segment_cache()` function that reloads from PostGIS and updates the in-memory store
- Call this automatically after the batch scorer (B3) completes a run
- Expose `POST /admin/cache/refresh` as a manually triggered refresh endpoint (no auth required for MVP — this is a local/personal deployment)
- Log cache load time and segment count on each refresh

**Startup behavior:**
- Cache is populated before the API begins accepting requests (block startup until load is complete)
- If the DB is unavailable at startup, fail fast with a clear error message rather than starting with an empty cache

**Completion criteria:**
- `GET /segments?bbox=...` response time < 50ms for any Jersey City viewport
- Full segment dataset is loaded into memory before the first request is served
- Cache refresh correctly picks up score changes made after the initial load
- `POST /admin/cache/refresh` triggers a reload and returns the new segment count and load time
- API startup fails with a descriptive error if PostGIS is unreachable

**Test cases:**
1. Start the API → logs show segment count and cache load time on startup (e.g. "Loaded 4,218 segments in 1.2s")
2. `GET /segments?bbox=...` for any Jersey City viewport → response time < 50ms (measure with `curl -w "%{time_total}"`)
3. Update a segment's `composite_score` directly in the DB, call `POST /admin/cache/refresh` → subsequent bbox response reflects the updated score
4. Run the batch scorer (B3) → cache refresh is triggered automatically, logged output confirms reload
5. Start the API with PostGIS unavailable → startup fails immediately with a clear error, does not start serving requests with empty data
6. `POST /admin/cache/refresh` → response body includes new segment count and time taken to reload

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
Initialize the React + TypeScript frontend with Vite. Configure Tailwind CSS, React Query, and React Router. Establish the base layout: a full-screen map area with a collapsible side panel.

Install MapLibre GL JS (`maplibre-gl`) instead of Mapbox. No API key or account required. Configure the tile source in a single constants file so it can be swapped later without touching component code.

Routes:
- `/` — map view (default)
- `/plan` — route planner panel open
- `/explore` — explore mode panel open
- `/login` and `/register` — auth screens

**Completion criteria:**
- `npm run dev` starts without errors
- `npm run typecheck` (`tsc --noEmit`) passes with zero errors in strict mode
- Tailwind classes apply correctly in the browser
- MapLibre GL JS is installed and the tile URL constant is defined (e.g. `TILE_URL = "https://tiles.openfreemap.org/styles/liberty"`)
- Base layout renders: full-screen map area + side panel visible on `/plan`

**Test cases:**
1. `npm run dev` → loads at localhost:5173 with no console errors
2. `npm run typecheck` → zero TypeScript errors
3. Navigate to `/plan` → side panel renders
4. Navigate to `/explore` → explore panel renders
5. Side panel is collapsible: toggle hides/shows it without breaking the map layout
6. No Mapbox token or environment variable is required anywhere in the codebase

---

### E2 — Map View & Aesthetic Overlay

**Description:**
Implement the map view using MapLibre GL JS with OpenFreeMap tiles. Street segments are rendered as a colored line layer sourced from `GET /segments?bbox=...`.

Implementation notes:
- Initialize the map with `new maplibregl.Map({ style: TILE_URL, ... })` — no token needed
- Fetch segments on map load and on `moveend` event (debounced 300ms)
- Add segments as a MapLibre GeoJSON source, then a `line` layer on top
- Base map style URL should use OpenFreeMap (e.g. `https://tiles.openfreemap.org/styles/liberty`)
- Color expression: MapLibre `interpolate` expression (identical syntax to Mapbox) mapping score 0–100 to the gradient in spec Section 4.3
- Unverified segments: `line-dasharray: [2, 2]`
- Verified segments: solid line
- Clicking a segment: use MapLibre's `map.on('click', layerId, ...)` to open a detail panel showing name, score, verification badge, vibe tag counts, rating count
- Toggle: show/hide overlay; show verified-only

**Completion criteria:**
- Map renders with OpenFreeMap tiles without any API key or token
- All segments in the current viewport render with the correct gradient color
- Unverified segments visually distinct (dashed), verified segments solid
- Segment click opens detail panel with correct data from `GET /segments/{id}`
- Overlay re-fetches on pan/zoom with 300ms debounce
- Toggle buttons correctly show/hide overlay and filter to verified-only

**Test cases:**
1. Load app over Jersey City waterfront → OpenFreeMap basemap renders and colored segment lines visible
2. A segment with score 85 renders deep green; a segment with score 15 renders red
3. An unverified segment renders dashed; a verified segment renders solid
4. Click a segment → detail panel appears with score, verified badge, and vibe tags
5. Toggle overlay off → colored lines disappear; toggle on → reappear
6. Pan map 500m → new segments load in the new viewport (confirmed via Network tab)
7. No requests to any Mapbox domain appear in the Network tab
---

### E2.1 — Map: Display Segment Name in Detail Panel

**Description:**
Update the segment detail panel to display `display_name` from the API response (requires C2.1) instead of the hardcoded "Unnamed segment" fallback. Surface the `highway` type as a secondary label beneath the name for additional context (e.g. "Residential street" in smaller text under "Grove Street").

**Completion criteria:**
- Detail panel always shows a meaningful name when a segment is clicked
- No instance of "Unnamed segment" appears in the UI for any named street
- `highway` type shown as a subtitle beneath the street name

**Test cases:**
1. Click a named street → panel header shows street name (e.g. "Grove Street")
2. Click an unnamed footpath → panel shows "Footway", not "Unnamed segment"
3. Click any segment → a non-empty `display_name` is always shown

### E2.2 — Map: Performance & Visibility Polish

**Description:**
Four UX issues to address: slow segment loading on initial load, 3D building extrusion making the overlay hard to read, insufficient click feedback on segment selection, and the detail panel failing to appear unless the side panel is already open.

**Visibility fixes:**
- On map `load`, remove all `fill-extrusion` layers from the OpenFreeMap liberty style to disable 3D buildings.
- Increase segment `line-width` to 3px at zoom 14, scaling to 5px at zoom 17 using a MapLibre zoom interpolation expression.

**Selection feedback fixes:**
- Change the cursor to a pointer (`cursor: pointer`) when hovering over any segment, so it is clear segments are clickable before the user clicks.

**Completion criteria:**
- No 3D building extrusion visible at any zoom level
- Segment lines clearly visible over the base map at zoom 14 and above
- Cursor changes to pointer on segment hover

**Test cases:**
1. Zoom to street level → no 3D buildings extruding; segment lines clearly distinguishable
2. Zoom interpolation: segment lines are 3px wide at zoom 14, 5px at zoom 17
3. Hover over a segment → cursor changes to pointer; move off → cursor returns to default
---

### E2.2a — Map: Segment Highlighting (Deferred)

**Description:**
Implement a distinct highlight style for the selected segment so users get immediate visual feedback on click.

**Implementation notes:**
- On segment click, apply a distinct highlight style to the selected segment: increase `line-width` by 2px and render in white or bright yellow, overlaid on top of the score color.
- Implement this as a separate MapLibre layer filtered to the selected `segment_id` so it doesn't interfere with the score color layer.

**Completion criteria:**
- Clicked segment is visually distinct from all other segments immediately on click
- Click a different segment → highlight moves to the new selection, previous segment returns to its score color

**Test cases:**
1. Click a segment → that segment immediately renders with a highlight style distinct from its neighbors
2. Click a different segment → highlight moves to the new selection, previous segment returns to its score color

---

### E2.2b — Map: Detail Panel Decoupling (Deferred)

**Description:**
Ensure the segment detail panel opens on click even when the side panel is closed. The detail panel must be an independent overlay anchored to the map.

**Implementation notes:**
- Decouple the detail panel's visibility from the side panel state.
- The detail panel should appear on click and dismiss on close or on clicking elsewhere on the map.

**Completion criteria:**
- Detail panel appears on segment click whether or not the side panel is open

**Test cases:**
1. Close the side panel entirely, click a segment → detail panel still appears
2. Click anywhere on the map outside a segment → detail panel dismisses

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
