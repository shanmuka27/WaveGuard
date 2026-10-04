from datetime import datetime, timedelta, timezone
import asyncio


from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import Database
from backend.routes import events
from backend.routes import scenarios
from backend.schemas import Reading, ReadingSource, Severity
from backend.services.event_service import EventService
from backend.services.incident_replay import build_replay
from backend.services.watsonx_client import build_granite_input


def test_detector_saves_a_frozen_mixed_source_window_and_replays_it(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "incidents.db"))
    database.initialize()
    service = EventService(database)
    monkeypatch.setattr(events, "database", database)
    app = FastAPI()
    app.include_router(events.router)
    client = TestClient(app)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    nodes = ["LUDINGTON-01", "MUSKEGON-02", "HOLLAND-03"]
    warning = None
    for step in range(12):
        for node in nodes:
            reading = Reading(
                node_id=node,
                timestamp=start + timedelta(seconds=step),
                water_level_cm=step * 1.4,
                quality=0.98,
                source=ReadingSource.PHYSICAL if node == nodes[0] else ReadingSource.SIMULATED,
            )
            event = service.ingest(reading)
            if event and event.severity == Severity.WARNING:
                warning = event
    assert warning is not None
    response = client.get(f"/api/events/{warning.event_id}/replay")
    assert response.status_code == 200
    replay = response.json()
    assert replay["storage"] == "sqlite"
    assert len(replay["nodes"]) == 3
    assert {node["source"] for node in replay["nodes"]} == {"physical", "simulated"}
    assert all(node["first_changed_at"] for node in replay["nodes"])
    assert "at least 3 abnormal nodes" in replay["detector_reason"]
    count = len(replay["readings"])

    service.ingest(Reading(node_id=nodes[0], timestamp=start + timedelta(minutes=1),
                           water_level_cm=0, quality=0.98, source=ReadingSource.PHYSICAL), detect=False)
    assert len(client.get(f"/api/events/{warning.event_id}/replay").json()["readings"]) == count
    saved = database.event_readings(warning.event_id)
    facts = build_granite_input(warning, {node.node_id: node.source.value for node in saved}, saved)
    assert len(facts["saved_reading_evidence"]) == 3
    assert facts["saved_reading_evidence"][0]["first_changed_at"] is not None


def test_old_events_without_evidence_have_no_replay(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "incidents.db"))
    database.initialize()
    monkeypatch.setattr(events, "database", database)
    app = FastAPI()
    app.include_router(events.router)
    client = TestClient(app)
    assert client.get("/api/events/missing/replay").status_code == 404


def test_neighbor_trigger_keeps_real_trace_and_labels_derived_nodes(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "mixed.db"))
    database.initialize()
    service = EventService(database)
    monkeypatch.setattr(scenarios, "event_service", service)
    monkeypatch.setattr(scenarios, "_current", {"scenario": "manual", "location": "LUDINGTON-01", "source_note": None})

    class Bridge:
        reference_distance_cm = 20.0
        def holding(self):
            return False

        async def set_board_node(self, node):
            self.board_node = node

    class Connections:
        async def broadcast(self, message):
            pass

    monkeypatch.setattr(scenarios, "serial_bridge", Bridge())
    monkeypatch.setattr(scenarios, "connections", Connections())
    from backend.routes.scenarios import playback

    levels = playback("seiche", "LUDINGTON-01")["LUDINGTON-01"]
    start = datetime.now(timezone.utc) - timedelta(seconds=11)
    for step, level in enumerate(levels[:12]):
        service.ingest(Reading(
            node_id="LUDINGTON-01", timestamp=start + timedelta(seconds=step),
            water_level_cm=level, quality=0.98, source=ReadingSource.PHYSICAL,
        ), detect=False)
    result = asyncio.run(scenarios.trigger_neighbor_response())
    assert result.event is not None and result.event.severity == Severity.WARNING
    saved = database.event_readings(result.event.event_id)
    assert len(saved) == 36
    assert sum(reading.source == ReadingSource.PHYSICAL for reading in saved) == 12
    assert sum(reading.source == ReadingSource.SIMULATED for reading in saved) == 24
    assert "derived from" in result.source_note
