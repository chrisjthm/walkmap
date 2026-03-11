from fastapi import BackgroundTasks, FastAPI

from app.ingest import DEFAULT_BBOX, BoundingBox, OSMDataProvider, ingest_segments
from app.score_batch import run_batch_scoring

app = FastAPI(title="Walkmap API")


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check for the API."""
    return {"status": "ok"}


@app.post("/admin/ingest/osm")
def ingest_osm(background_tasks: BackgroundTasks) -> dict[str, str | dict[str, float]]:
    """Queue a background ingest of OSM walkable segments for the MVP bbox.

    This endpoint is intended for manual/admin use to populate the `segments`
    table with OSM data (e.g., during initial setup or when refreshing data).
    It currently takes no request body; it always uses the configured MVP
    bounding box from `DEFAULT_BBOX`.
    """
    bbox = BoundingBox(**DEFAULT_BBOX)
    provider = OSMDataProvider()
    background_tasks.add_task(ingest_segments, bbox, provider)
    return {"status": "queued", "bbox": DEFAULT_BBOX}


@app.post("/admin/score/batch")
def score_batch(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Queue a background scoring run for unscored segments.

    This endpoint is intended for manual/admin use to apply AI scores
    to any segments that still have ai_score = NULL.
    """
    background_tasks.add_task(run_batch_scoring)
    return {"status": "queued"}
