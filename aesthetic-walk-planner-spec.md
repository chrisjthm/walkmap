# Aesthetic Walk & Run Planner — Product Specification

**Version:** 0.1 (MVP)  
**Status:** Draft  
**Target:** Personal beta (Downtown Jersey City / Waterfront area)

---

## 1. Overview

A web-based urban walk and run planner that helps users discover aesthetically pleasing routes through cities. Unlike navigation tools that optimize for speed, this app optimizes for *experience* — surfacing streets with interesting architecture, lively businesses, quiet tree-lined blocks, or scenic waterfronts, and avoiding highways, blank walls, and hostile pedestrian infrastructure.

The core mechanic is a crowd-sourced aesthetic rating layer overlaid on a map, where individual street segments are colored on a green-to-red gradient. Routes are suggested by maximizing the aesthetic score of streets traversed, subject to user-defined constraints (time, distance, mode, priority).

---

## 2. Problem Statement

Existing navigation tools (Google Maps, Apple Maps) optimize for efficiency. Wandering apps (AllTrails, Komoot) are built for nature trails, not urban grids. There is no tool that helps a person in an unfamiliar — or familiar — city answer: *"Where should I walk if I want it to feel good?"*

This problem is particularly acute for:
- Tourists who want to explore beyond the hotel
- Couples looking for a walk to a dinner spot, choosing based on feel
- Residents who want to discover new pockets of their own neighborhood
- Runners who want a route that feels pleasant, not just measured

---

## 3. Target Users

**MVP (personal beta):**
- One or two users (app creator + partner), Downtown Jersey City / Waterfront

**Future:**
- Urban walkers and joggers in any city
- Tourists and city visitors
- Neighborhood explorers

---

## 4. Core Concepts

### 4.1 Street Segment
The atomic unit of the app. A street segment is the section of road between two consecutive intersections — derived from OpenStreetMap (OSM) data. Each segment has:
- A geometry (lat/lng polyline)
- OSM metadata (road type, name, sidewalk presence, surface, etc.)
- A composite **Aesthetic Score** (0–100)
- A **verification status**: `unverified` (AI-only) or `verified` (at least one real user rating)
- Zero or more **user ratings**
- Aggregated **vibe tags**

### 4.2 Aesthetic Score
A numeric score from 0 (very unpleasant) to 100 (highly aesthetic), computed as a weighted blend of:
- The AI-generated base score (see Section 7)
- User ratings, when present (user ratings override and progressively replace the AI baseline)

The score determines segment color on the map overlay.

### 4.3 Score Color Gradient
| Score | Color | Meaning |
|---|---|---|
| 80–100 | Deep green | Highly aesthetic |
| 60–79 | Light green | Pleasant |
| 40–59 | Yellow | Neutral / mixed |
| 20–39 | Orange | Unpleasant |
| 0–19 | Red | Avoid |
| Unverified | Muted/hatched | AI estimate only |

Unverified segments use a desaturated or hatched version of the same color to visually distinguish them from verified ones.

---

## 5. Features

### 5.1 Map View
- Interactive map (Mapbox GL JS) centered on user's location or a searched address
- Street segments colored by aesthetic score
- Toggle to show/hide the aesthetic overlay
- Toggle to show only verified vs. all segments
- Tap a segment to see its score, verification status, vibe tags, and rating count
- Tap to open a rating panel for that segment

### 5.2 Route Planner
**Inputs:**
| Field | Options |
|---|---|
| Starting point | Current location or typed address |
| Route type | Loop (return to start) · Point-to-point (open ended) · Point-to-destination (specific end address) |
| Duration or distance | Slider: 15 min – 3 hrs, or 0.5 – 15 miles |
| Activity | Walk · Run |
| Priority mode | Highest rated · Bars/restaurants/shopping · Residential/quiet · Explore (unverified) |

**Output:**
- 2–3 suggested routes displayed on map
- Each route labeled with: total distance, estimated time, average aesthetic score, number of verified vs. unverified segments
- Routes are meaningfully differentiated (see Section 5.2.1)
- Tap a route to preview it; confirm to start navigation

#### 5.2.1 Route Differentiation
When multiple routes are returned, they must minimize segment overlap. The system generates candidates using variations in:
- Directional bias (different compass quadrants explored)
- Score weighting (one pure top-score, one balanced, one exploratory)
- Loop shape (figure-8, single loop, out-and-back hybrid)

### 5.3 Rating System
After walking a route (or at any time on the map), users can rate street segments.

**Rating flow:**
1. User taps a segment on the map (or segments are surfaced post-walk based on route)
2. Thumbs up / thumbs down prompt appears
3. Optional: multi-select vibe tags (see Section 5.3.1)
4. Submit — rating is stored and score is recalculated

#### 5.3.1 Vibe Tags
Suggested tags, groupable by category. User can select multiple:

**Positive tags:** Scenic · Tree-lined · Lively · Great architecture · Waterfront · Charming · Quiet & peaceful · Good food nearby · Dog-friendly · Art & murals

**Negative tags:** Loud traffic · No sidewalk · Industrial/boring · Feels unsafe · Construction · No shade

Tags are displayed in aggregate on the segment info panel, ordered by frequency.

### 5.4 Post-Walk Rating Flow
After a walk is completed (or manually triggered), the app surfaces the 3–5 most impactful unrated or underrated segments from the route for quick rating. This maximizes crowd-sourced data quality by directing attention to high-value segments.

### 5.5 Explore Mode
A dedicated map mode that highlights segments with high aesthetic potential but no user verification. The user can browse and walk these to contribute ratings. Prioritizes:
1. Segments adjacent to already-verified high-scoring segments
2. Segments with high AI confidence in their score
3. Segments that have been walked by users but not rated

### 5.6 Authentication (MVP)
- Simple email + password registration and login
- No social login required for MVP
- Session persists via JWT or cookie
- Single user profile per account
- Ratings are attributed to the authenticated user

---

## 6. Data Architecture

### 6.1 Data Sources
The system is designed to be **data-source agnostic**. The scoring pipeline uses an abstract `DataProvider` interface so that underlying sources can be swapped without changing routing or scoring logic.

**MVP data sources:**
- **OpenStreetMap (Overpass API):** Free. Provides road type, sidewalk tags, surface type, name, landuse. Used for base structural scoring.
- **OpenStreetMap POI data:** Free. Shops, restaurants, cafes, parks, etc. within a radius of each segment.

**Pluggable future sources:**
- Google Places API (richer POI data, ratings)
- Foursquare / Yelp (vibe categorization, popularity)
- Street View + ML vision scoring (image-based aesthetics)
- Mapillary (open street-level imagery)

### 6.2 Schema (Simplified)

```
Segment
  id: string (OSM way ID + node pair)
  geometry: LineString
  osm_tags: JSON
  ai_score: float (0–100)
  ai_confidence: float (0–1)
  user_score: float | null
  composite_score: float
  verified: boolean
  rating_count: int
  vibe_tags: { tag: string, count: int }[]
  last_updated: timestamp

Rating
  id: uuid
  segment_id: string
  user_id: uuid
  thumbs_up: boolean
  vibe_tags: string[]
  created_at: timestamp

User
  id: uuid
  email: string
  password_hash: string
  created_at: timestamp

Route (saved/history)
  id: uuid
  user_id: uuid
  start_point: Point
  end_point: Point | null
  mode: loop | point-to-point | point-to-destination
  priority: highest-rated | dining | residential | explore
  segments: string[]
  distance_m: float
  duration_s: int
  avg_score: float
  created_at: timestamp
```

---

## 7. AI Scoring Engine

### 7.1 Design Principles
- Scores are generated at ingest time (or on-demand for new areas), not at query time
- The engine is a stateless function: `score(segment_osm_tags, nearby_pois) → { score: float, confidence: float, factors: JSON }`
- Scores are stored and refreshed periodically (e.g., nightly or on new user activity in an area)
- User ratings progressively override the AI baseline using a weighted average

### 7.2 Scoring Factors

Each factor contributes a weighted sub-score. Weights are tunable via config (not hardcoded):

| Factor | Signal | Direction |
|---|---|---|
| Road type | `highway=footway/path/residential` | ↑ positive |
| Road type | `highway=trunk/motorway/primary` | ↓ negative |
| Sidewalk presence | `sidewalk=both/left/right` | ↑ positive |
| Sidewalk presence | `sidewalk=no` | ↓ negative |
| Surface quality | `surface=paved/asphalt/cobblestone` | neutral / slight positive |
| Surface quality | `surface=dirt/gravel` on urban segments | ↓ slight negative |
| Tree cover (proxy) | `natural=tree_row` or park adjacency | ↑ positive |
| Waterfront | proximity to `natural=water` or `waterway` | ↑ positive |
| Business density | count of restaurants/cafes/shops within 30m | ↑ positive (up to a threshold) |
| Park adjacency | within 50m of `leisure=park` | ↑ positive |
| Industrial land use | `landuse=industrial/commercial/parking` | ↓ negative |
| Residential land use | `landuse=residential` + low traffic road | ↑ positive |
| Speed limit (proxy) | `maxspeed` > 45mph | ↓ negative |

### 7.3 Score Blending (AI + User)

```
if rating_count == 0:
    composite_score = ai_score
    verified = false
elif rating_count < 5:
    composite_score = (ai_score * (5 - rating_count) + user_score * rating_count) / 5
    verified = true
else:
    composite_score = user_score
    verified = true
```

`user_score` = percentage of thumbs-up ratings × 100, smoothed against a prior of 50 for low sample sizes.

### 7.4 Confidence Score
AI confidence is higher when:
- More OSM tags are present for the segment
- Road type is unambiguous
- POI data is dense (indicative of a well-mapped area)

Low confidence segments are visually flagged and prioritized for user exploration.

---

## 8. Routing Engine

### 8.1 Approach
Custom graph-based routing over the OSM pedestrian network.

- Build a weighted directed graph where **edge weight = (1 - normalized_score)**
- Apply a penalty multiplier based on priority mode (e.g., in dining mode, boost edges near restaurants)
- Use a modified Dijkstra or A* to find lowest-weight paths
- For loop routes: solve as a Traveling Salesman approximation with a distance constraint, biasing toward unvisited high-score segments
- For multi-route output: generate N candidates using different seed directions, then prune for overlap using Jaccard similarity on segment sets

### 8.2 Priority Mode Modifiers

| Mode | Weight Adjustment |
|---|---|
| Highest rated | Pure score maximization |
| Dining/shopping | Bonus weight to segments within 50m of restaurants, cafes, bars, retail |
| Residential | Bonus weight to `landuse=residential` + `highway=residential/living_street` |
| Explore | Invert weighting: prioritize segments with `verified=false` and high AI confidence |

### 8.3 Constraints
- Pedestrian-only graph (no highways, no roads without sidewalks unless no alternative)
- Hard cap on distance deviation: route distance must be within ±15% of user-specified target
- Routes must be topologically valid (connected, no dead ends unless point-to-point)

---

## 9. Technical Stack

| Layer | Technology | Rationale |
|---|---|---|
| Frontend | React + TypeScript | Component model fits the map + panel UI |
| Map | Mapbox GL JS | Best-in-class vector tile rendering; custom segment color layers are a first-class feature |
| Styling | Tailwind CSS | Utility-first; no design decisions required |
| Data fetching | React Query | Caching, background refresh, loading states with minimal boilerplate |
| Backend | Python 3.12 + FastAPI | Native fit with the geospatial/OSM ecosystem; async support |
| OSM ingest + graph | OSMnx | Fetches OSM data and builds a pedestrian NetworkX graph in a few lines |
| Routing | NetworkX | A* and Dijkstra built-in; operates directly on OSMnx graph |
| Geometry | Shapely | Segment proximity, buffer calculations, geometry ops |
| ORM + DB bridge | SQLAlchemy (async) + GeoAlchemy2 | PostGIS-native types, async queries |
| Database | PostgreSQL 16 + PostGIS | Geospatial indexing, proximity queries, segment storage |
| Auth | bcrypt + PyJWT | Stateless, no external dependencies |
| Local dev | Docker Compose | Single command spins up Postgres + API + frontend |
| Hosting (backend) | Railway or Render | Free tier sufficient for personal MVP |
| Hosting (frontend) | Vercel | Free tier, automatic deploys from Git |

### Stack Rationale: Python over Java/Go

Python was selected over Java (Spring Boot) and Go for this project:

- **OSMnx** handles OSM data ingest, pedestrian graph construction, and nearest-node snapping in a few lines — replacing weeks of custom plumbing in any other language
- **NetworkX** provides A*, Dijkstra, and graph traversal built-in, operating directly on the OSMnx graph
- **Shapely + GeoAlchemy2** give native PostGIS type support with minimal glue code
- Go has the thinnest geospatial ecosystem of the three and would require building significant infrastructure from scratch
- Java (Spring Boot) is viable but the OSMnx/Shapely/NetworkX equivalents require substantially more boilerplate; the productivity gap is significant for a geospatial-heavy MVP

---

## 10. MVP Scope (Jersey City Personal Beta)

### In Scope
- Map view with aesthetic overlay for Downtown Jersey City / Waterfront bounding box
- AI scoring seeded from OSM data for all pedestrian segments in the area
- Route planner: loop mode, point-to-point, point-to-destination
- Priority modes: highest rated, dining/shopping, residential, explore
- Thumbs up/down rating with vibe tags
- Post-walk rating prompt
- Simple email/password auth (2 user accounts)
- 2–3 route suggestions with score and distance summary

### Out of Scope (Post-MVP)
- Real-time navigation / turn-by-turn
- Social features (following users, shared routes)
- Multiple cities (auto-expanding coverage)
- Mobile app (native)
- Google Places / paid API integration
- ML image scoring via Street View
- Route sharing / export to other apps
- Accessibility routing (wheelchair, stroller)

---

## 11. Phased Roadmap

### Phase 0 — Local Seed (Week 1–2)
- Ingest OSM data for Jersey City bounding box
- Run AI scoring pipeline, store segment scores
- Basic map rendering with score overlay

### Phase 1 — Route Planning (Week 3–4)
- Implement routing graph over pedestrian network
- Build route planner UI (inputs + map output)
- Basic loop + point-to-point routing with score optimization

### Phase 2 — Rating System (Week 5–6)
- Auth (email/password)
- Segment tap → rating panel → thumbs/tags → submit
- Score recalculation on new rating
- Post-walk rating prompt

### Phase 3 — Polish & Personal Beta (Week 7–8)
- Explore mode
- Multi-route output with differentiation
- Visual polish (gradient colors, verified vs unverified styling)
- Mobile-responsive layout
- Personal testing with real walks

### Phase 4 — Productionization (Future)
- Expand to additional cities / dynamic area loading
- Pluggable data provider for Google Places, Yelp
- Native mobile app
- Public user registration

---

## 12. Open Questions & Risks

| Item | Notes |
|---|---|
| OSM coverage quality | Jersey City is well-mapped, but sidewalk tags may be sparse. May need manual review or fallback heuristics. |
| Routing performance | PostGIS + pgRouting should handle the small area easily; will need profiling at city scale. |
| "Aesthetic" subjectivity | The same block can be loved by one person and disliked by another. Vibe tags help capture this nuance better than a single score. Consider per-user personalization as a v2 feature. |
| Cold start quality | The first few walks rely entirely on AI scores. Score calibration against real walks in Jersey City should happen in Phase 3 to tune factor weights. |
| Mapbox cost | Mapbox free tier (50k map loads/month) is more than sufficient for personal MVP. Revisit at scale. |
| Data freshness | OSM data changes. Plan a periodic re-ingest job (weekly for MVP area). |
