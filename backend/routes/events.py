from fastapi import APIRouter, HTTPException, Query

from backend.runtime import database
from backend.schemas import Event
from backend.services.incident_replay import IncidentReplay, build_replay

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[Event])
def list_events(limit: int = Query(default=50, ge=1, le=500)) -> list[Event]:
    return database.events(limit)


@router.get("/latest", response_model=Event)
def latest_event() -> Event:
    events = database.events(1)
    if not events:
        raise HTTPException(status_code=404, detail="No events have been detected")
    return events[0]


@router.get("/{event_id}/replay", response_model=IncidentReplay)
def replay_event(event_id: str) -> IncidentReplay:
    event = database.event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    readings = database.event_readings(event_id)
    if not readings:
        raise HTTPException(status_code=404, detail="No saved reading window for this event")
    return build_replay(event, readings, database.storage)


@router.get("/{event_id}", response_model=Event)
def get_event(event_id: str) -> Event:
    event = database.event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
