from fastapi import FastAPI

app = FastAPI(
    title="WaveGuard API",
    description="Coastal hazard readings, event detection, and response API.",
    version="0.1.0",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a small response that teammates can use for connection checks."""
    return {"status": "ok", "service": "waveguard"}
