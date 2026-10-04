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
        if hasattr(database, "close"):
            database.close()

app = FastAPI(
    title="WaveGuard API",
    description="Coastal hazard readings, event detection, and response API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    # Phone mode (start-demo.bat phone): pages served to devices on the same
    # private network, e.g. http://192.168.1.20:5500.
    allow_origin_regex=r"http://(10\.\d+|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d+\.\d+:(3000|5500)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(readings.router)
app.include_router(nodes.router)
app.include_router(events.router)
app.include_router(scenarios.router)
app.include_router(scenarios.board_router)
app.include_router(scenarios.sensor_router)
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
