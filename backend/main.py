import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import agent_tools, events, nodes, readings, scenarios
from backend.runtime import connections, database, serial_bridge


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    serial_task = (
        asyncio.create_task(serial_bridge.run()) if serial_bridge.port else None
    )
    try:
        yield
    finally:
        if serial_task is not None:
            serial_task.cancel()
            await asyncio.gather(serial_task, return_exceptions=True)

app = FastAPI(
    title="WaveGuard API",
    description="Coastal hazard readings, event detection, and response API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(readings.router)
app.include_router(nodes.router)
app.include_router(events.router)
app.include_router(scenarios.router)
app.include_router(agent_tools.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a small response that teammates can use for connection checks."""
    return {"status": "ok", "service": "waveguard"}


@app.websocket("/ws/live")
async def live_updates(websocket: WebSocket) -> None:
    await connections.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.disconnect(websocket)
