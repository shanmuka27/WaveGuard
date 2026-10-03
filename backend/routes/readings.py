from fastapi import APIRouter, Query

from backend.runtime import connections, database, event_service, serial_bridge
from backend.schemas import IngestResult, Reading

router = APIRouter(prefix="/api/readings", tags=["readings"])


@router.post("", response_model=IngestResult)
async def submit_reading(reading: Reading) -> IngestResult:
    event = event_service.ingest(reading)
    await connections.broadcast(
        {
            "type": "reading",
            "reading": reading.model_dump(mode="json"),
            "event": event.model_dump(mode="json") if event else None,
        }
    )
    await serial_bridge.send_state(event_service.overall_severity())
    return IngestResult(reading=reading, event=event)


@router.get("/latest", response_model=list[Reading])
def latest_readings(limit: int = Query(default=100, ge=1, le=1000)) -> list[Reading]:
    return database.latest_readings(limit)
