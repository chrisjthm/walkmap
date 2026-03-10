from fastapi import FastAPI

app = FastAPI(title="Walkmap API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
