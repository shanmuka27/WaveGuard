from datetime import datetime, timedelta, timezone
from math import pi, sin

from fastapi import APIRouter, HTTPException

from backend.runtime import connections, event_service
from backend.schemas import Reading, ReadingSource, ScenarioResult

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

SCENARIOS = {"normal", "local_disturbance", "seiche", "sudden_surge"}
NODES = (
    ("LUDINGTON-01", ReadingSource.PHYSICAL),
    ("MUSKEGON-02", ReadingSource.SIMULATED),
    ("HOLLAND-03", ReadingSource.SIMULATED),
)


def _level(scenario: str, node_index: int, step: int) -> float:
    baseline = 14.0 + node_index * 0.3
    if scenario == "normal":
        return baseline + 0.15 * sin(step * pi / 4)
    if scenario == "local_disturbance":
        return baseline + (4.0 * sin(step * pi / 3) if node_index == 0 else 0.1)
    if scenario == "seiche":
        return baseline + 3.5 * sin(step * pi / 3)
    return baseline + max(0, step - 5) * 1.4


@router.post("/{scenario}", response_model=ScenarioResult)
async def run_scenario(scenario: str) -> ScenarioResult:
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=404, detail=f"Scenario must be one of: {', '.join(sorted(SCENARIOS))}"
        )

    event_service.reset_live_state()
    start = datetime.now(timezone.utc) - timedelta(seconds=11)
    generated = 0
    for step in range(12):
        for node_index, (node_id, source) in enumerate(NODES):
            reading = Reading(
                node_id=node_id,
                timestamp=start + timedelta(seconds=step),
                water_level_cm=round(_level(scenario, node_index, step), 3),
                quality=0.98,
                source=source,
            )
            event_service.ingest(reading, detect=False)
            generated += 1

    latest_event = event_service.detect_event()

    await connections.broadcast(
        {
            "type": "scenario_complete",
            "scenario": scenario,
            "event": latest_event.model_dump(mode="json") if latest_event else None,
        }
    )
    return ScenarioResult(
        scenario=scenario, readings_generated=generated, event=latest_event
    )
