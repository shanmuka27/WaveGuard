from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from math import asin, cos, pi, radians, sin, sqrt
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.runtime import connections, database, event_service, serial_bridge
from backend.schemas import Reading, ReadingSource, ScenarioResult
from backend.services.replay import describe, gauge_series, replay_length
from backend.detection.event_classifier import classify_node
from backend.schemas import EventClassification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])
board_router = APIRouter(prefix="/api/board", tags=["board"])
sensor_router = APIRouter(prefix="/api/sensor", tags=["sensor"])
view_router = APIRouter(prefix="/api/view", tags=["view"])

# "manual" is the live mode: the physical station shows real sensor readings while
# every other node replays a calm real record.
SCENARIOS = {"normal", "local_disturbance", "seiche", "sudden_surge", "manual"}
NODES = (
    ("LUDINGTON-01", ReadingSource.SIMULATED),
    ("MUSKEGON-02", ReadingSource.SIMULATED),
    ("HOLLAND-03", ReadingSource.SIMULATED),
    ("GRANDHAVEN-04", ReadingSource.SIMULATED),
    ("SOUTHHAVEN-05", ReadingSource.SIMULATED),
    ("MANISTEE-06", ReadingSource.SIMULATED),
)

# Tabletop scale: levels are cm relative to calm water in the demo tray, the same
# zero the calibrated physical sensor reports, and stay inside its ~+9 cm reach.
# Amplitudes sit just above the detector's thresholds (seiche >= 2 cm peak to
# trough, sudden surge >= 1.2 cm/s and >= 3 cm total) so each scenario still
# classifies as intended.
DISTURBANCE_AMPLITUDE_CM = 2.0

# Shoreline positions, used to find which neighbours a localized event reaches.
NODE_COORDS = {
    "LUDINGTON-01": (43.9553, -86.4526),
    "MUSKEGON-02": (43.2342, -86.2484),
    "HOLLAND-03": (42.7725, -86.2119),
    "GRANDHAVEN-04": (43.0567, -86.2486),
    "SOUTHHAVEN-05": (42.4031, -86.2861),
    "MANISTEE-06": (44.2483, -86.3439),
}

# Whole-shoreline runs: per-node (seiche amplitude scale, surge rise in cm per step)
# so the coast doesn't move in lockstep.
NODE_RESPONSE = (
    (1.00, 1.30),
    (0.85, 1.25),
    (1.15, 1.45),
    (0.90, 1.30),
    (1.10, 1.40),
    (0.80, 1.25),
)

# Localized runs: the chosen location, then its nearest and second-nearest
# neighbours, each a little weaker. Three correlated nodes is what the detector
# needs for a warning, so a localized seiche or surge warns only that stretch of
# shore and every other node stays calm.
RANKED_RESPONSE = ((1.00, 1.45), (0.90, 1.35), (0.80, 1.25))
NEIGHBOURS_REACHED = 2


def _distance_km(a: str, b: str) -> float:
    (lat1, lon1), (lat2, lon2) = NODE_COORDS[a], NODE_COORDS[b]
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def nearest_nodes(node_id: str, count: int) -> list[str]:
    others = [other for other, _ in NODES if other != node_id]
    return sorted(others, key=lambda other: _distance_km(node_id, other))[:count]


def scenario_responses(
    scenario: str, location: Optional[str]
) -> dict[str, tuple[float, float]]:
    """Nodes the scenario moves and how strongly; nodes left out stay calm."""
    if scenario == "normal":
        return {}
    if scenario == "local_disturbance":
        return {location or NODES[0][0]: RANKED_RESPONSE[0]}
    if location is None:
        return {node_id: response for (node_id, _), response in zip(NODES, NODE_RESPONSE)}
    reached = [location, *nearest_nodes(location, NEIGHBOURS_REACHED)]
    return dict(zip(reached, RANKED_RESPONSE))


# The physical station's scenario data is shaped like its tray sensor: same zero,
# no higher than the gap between calm water and the sensor's ~2.5 cm blind spot,
# and in the ~0.43 cm steps (plus a little jitter) the real readings arrive in.
PHYSICAL_NODE = "LUDINGTON-01"
SENSOR_BLIND_SPOT_CM = 2.5
SENSOR_STEP_CM = 0.43


def _sensor_headroom() -> float:
    return max(serial_bridge.reference_distance_cm - SENSOR_BLIND_SPOT_CM, 3.5)


def _as_physical_sensor(series: list[float]) -> list[float]:
    """Reshape demo levels the way the tray sensor would report them: shrunk to fit
    under its blind spot (rather than clipped flat), with its echo jitter, in its
    measurement steps."""
    peak = max(series)
    fit = min(1.0, 0.85 * _sensor_headroom() / peak) if peak > 0 else 1.0
    return [
        round((value * fit + 0.3 * sin(step * 2.7)) / SENSOR_STEP_CM) * SENSOR_STEP_CM
        for step, value in enumerate(series)
    ]


SEED_STEPS = 12  # replayed instantly so the detector has a window right away
SURGE_RISE_STEPS = 6


def playback(scenario: str, location: Optional[str]) -> dict[str, list[float]]:
    """Every node's level for each replayed second of the scenario.

    Affected nodes replay their nearest NOAA gauge's real record of that kind of
    event; calm nodes replay a calm real record. Two kinds stay synthetic on top of
    the calm record: a local disturbance (a wake or splash at one harbor, which no
    gauge records) and a sudden surge (which 6-minute gauge readings average away).
    The physical station's data is reshaped to what its tray sensor would report.
    """
    responses = {} if scenario == "manual" else scenario_responses(scenario, location)
    steps = replay_length()
    levels: dict[str, list[float]] = {}
    for node_id, _ in NODES:
        response = responses.get(node_id)
        calm = gauge_series("normal", node_id)
        if response is None:
            series = calm
        elif scenario == "local_disturbance":
            series = [DISTURBANCE_AMPLITUDE_CM * sin(step * pi / 3) for step in range(steps)]
        elif scenario == "sudden_surge":
            # Fast rise over SURGE_RISE_STEPS, then the water stays up.
            rate = response[1]
            series = [
                min(max(0, step - 5), SURGE_RISE_STEPS) * rate + calm[step] for step in range(steps)
            ]
        else:
            series = [value * response[0] for value in gauge_series(scenario, node_id)]
        if node_id == PHYSICAL_NODE:
            series = _as_physical_sensor(series)
        levels[node_id] = series
    return levels


def source_note(scenario: str, location: Optional[str]) -> Optional[str]:
    note = describe("seiche" if scenario == "seiche" else "normal")
    if note and scenario == "manual":
        return "Ludington shows the live tray sensor. Other nodes: " + note[0].lower() + note[1:]
    if note and scenario == "local_disturbance":
        place = (location or NODES[0][0]).split("-")[0].title()
        note += f"; the disturbance at {place} is synthetic"
    if note and scenario == "sudden_surge":
        note += "; the surge itself is synthetic (6-minute gauge readings average sudden surges away)"
    return note


def _reading(node_id: str, source: ReadingSource, level: float, at: datetime) -> Reading:
    return Reading(
        node_id=node_id, timestamp=at, water_level_cm=round(level, 3), quality=0.98, source=source
    )


_playback_task: Optional[asyncio.Task] = None
_current: dict = {"scenario": None, "location": None, "source_note": None}
_neighbor_response_until = 0.0
NEIGHBOR_RESPONSE_HOLD_SECONDS = 30


def _loop_index(scenario: str, step: int) -> int:
    """Replay index for a step: after the first pass, keep cycling the replay (a surge
    keeps cycling its high-water plateau) so the scenario plays until switched."""
    length = replay_length()
    if step < length:
        return step
    loop_start = SURGE_LOOP_START if scenario == "sudden_surge" else SEED_STEPS
    return loop_start + (step - length) % (length - loop_start)


SURGE_LOOP_START = 18  # after the rise: the water stays high


async def _stream_playback(scenario: str, levels: dict[str, list[float]]) -> None:
    """Play the scenario live, one reading per node per second, until switched."""
    try:
        step = SEED_STEPS
        while True:
            await asyncio.sleep(1)
            now = datetime.now(timezone.utc)
            index = _loop_index(scenario, step)
            step += 1
            for node_id, source in NODES:
                # In manual mode the physical station is the live sensor.
                if node_id == PHYSICAL_NODE and not serial_bridge.holding():
                    continue
                if (scenario == "manual" and node_id in nearest_nodes(PHYSICAL_NODE, 2)
                        and time.monotonic() < _neighbor_response_until):
                    continue
                reading = _reading(node_id, source, levels[node_id][index], now)
                event = event_service.ingest(reading)
                await connections.broadcast(
                    {
                        "type": "reading",
                        "reading": reading.model_dump(mode="json"),
                        "event": event.model_dump(mode="json") if event else None,
                    }
                )
            await serial_bridge.sync_state()
    except asyncio.CancelledError:
        raise
    except Exception:  # keep the API up even if a replay step fails
        logger.exception("Scenario playback stopped")


@router.post("/{scenario}", response_model=ScenarioResult)
async def run_scenario(
    scenario: str,
    location: Optional[str] = Query(
        default=None, description="Node to center the scenario on; omit for the whole shoreline"
    ),
) -> ScenarioResult:
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=404, detail=f"Scenario must be one of: {', '.join(sorted(SCENARIOS))}"
        )
    if location is not None and location not in NODE_COORDS:
        raise HTTPException(
            status_code=404, detail=f"Location must be one of: {', '.join(NODE_COORDS)}"
        )
    global _playback_task
    global _neighbor_response_until
    if _playback_task is not None:
        _playback_task.cancel()
    _neighbor_response_until = 0.0
    levels = playback(scenario, location)
    note = source_note(scenario, location)
    _current.update(scenario=scenario, location=location, source_note=note)

    serial_bridge.pause_physical(scenario != "manual")
    event_service.reset_live_state()
    start = datetime.now(timezone.utc) - timedelta(seconds=SEED_STEPS - 1)
    generated = 0
    for step in range(SEED_STEPS):
        for node_id, source in NODES:
            if node_id == PHYSICAL_NODE and scenario == "manual":
                continue
            at = start + timedelta(seconds=step)
            event_service.ingest(_reading(node_id, source, levels[node_id][step], at), detect=False)
            generated += 1

    latest_event = event_service.detect_event()
    await serial_bridge.set_board_node(location)  # the board reacts first
    await asyncio.to_thread(event_service.flush_readings)  # then one batch save

    await connections.broadcast(
        {
            "type": "scenario_complete",
            "scenario": scenario,
            "location": location,
            "source_note": note,
            "event": latest_event.model_dump(mode="json") if latest_event else None,
        }
    )
    _playback_task = asyncio.create_task(_stream_playback(scenario, levels))
    return ScenarioResult(
        scenario=scenario,
        location=location,
        readings_generated=generated,
        source_note=note,
        event=latest_event,
    )


@sensor_router.post("/neighbor-response", response_model=ScenarioResult)
async def trigger_neighbor_response() -> ScenarioResult:
    """Replay the recent real Ludington shape on two labeled simulated neighbors."""
    global _neighbor_response_until
    if _current["scenario"] != "manual" or serial_bridge.holding():
        raise HTTPException(status_code=409, detail="Start Manual mode with the Arduino first.")
    physical = [
        reading for reading in event_service.histories[PHYSICAL_NODE]
        if reading.source == ReadingSource.PHYSICAL and reading.quality > 0.5
    ][-SEED_STEPS:]
    if len(physical) < SEED_STEPS or (
        datetime.now(timezone.utc) - physical[-1].timestamp
    ).total_seconds() > 5:
        raise HTTPException(status_code=409, detail="Need 12 recent good Arduino readings first.")
    if classify_node(physical).classification == EventClassification.NORMAL:
        raise HTTPException(status_code=409, detail="Move the water until the live Ludington trace changes, then retry.")

    neighbors = nearest_nodes(PHYSICAL_NODE, 2)
    event_service.reset_node_signals(neighbors)
    # This is a response simulation driven by the observed physical waveform,
    # not independent evidence from real sensors at the other locations.
    generated = 0
    generated_readings = []
    for reading in physical:
        for index, node_id in enumerate(neighbors):
            simulated = _reading(
                node_id, ReadingSource.SIMULATED,
                reading.water_level_cm * (0.95 if index == 0 else 1.05),
                reading.timestamp,
            )
            event_service.ingest(simulated, detect=False)
            generated += 1
            generated_readings.append(simulated)
    event = event_service.detect_event()
    _neighbor_response_until = time.monotonic() + NEIGHBOR_RESPONSE_HOLD_SECONDS
    note = ("Ludington is the live Arduino trace. The two neighboring traces are "
            "simulated responses derived from its recent waveform, not independent physical sensors.")
    _current["source_note"] = note
    for simulated in generated_readings:
        await connections.broadcast({
            "type": "reading", "reading": simulated.model_dump(mode="json"), "event": None,
        })
    await serial_bridge.set_board_node(PHYSICAL_NODE)
    # Pages reload readings on scenario_complete: save the batch first.
    await asyncio.to_thread(event_service.flush_readings)
    await connections.broadcast({
        "type": "scenario_complete", "scenario": "neighbor_response",
        "location": PHYSICAL_NODE, "source_note": note,
        "event": event.model_dump(mode="json") if event else None,
    })
    return ScenarioResult(
        scenario="neighbor_response", location=PHYSICAL_NODE, source_note=note,
        readings_generated=generated, event=event,
    )


@router.get("/current")
def current_scenario() -> dict:
    """The last scenario started and what data it replays (for pages opened mid-demo)."""
    return dict(_current)


@board_router.get("")
def board_location() -> dict:
    """Location whose status the physical board shows (null = whole network)."""
    return {"location": serial_bridge.board_node}


@board_router.put("")
async def set_board_location(
    location: Optional[str] = Query(default=None, description="Node id; omit for the whole network"),
) -> dict:
    if location is not None and location not in NODE_COORDS:
        raise HTTPException(
            status_code=404, detail=f"Location must be one of: {', '.join(NODE_COORDS)}"
        )
    await serial_bridge.set_board_node(location)
    return {"location": serial_bridge.board_node}


CALIBRATION_WINDOW_S = 15
CALIBRATION_MIN_READINGS = 8


def _persist_reference(reference_cm: float) -> None:
    """Keep the new zero across restarts by updating REFERENCE_DISTANCE_CM in .env."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    lines = env.read_text(encoding="utf-8").splitlines()
    found = False
    for index, line in enumerate(lines):
        if line.startswith("REFERENCE_DISTANCE_CM="):
            lines[index] = f"REFERENCE_DISTANCE_CM={reference_cm}"
            found = True
    if not found:
        lines.append(f"REFERENCE_DISTANCE_CM={reference_cm}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")


@sensor_router.get("")
def sensor_status() -> dict:
    """The physical sensor's latest reading and calibration, for the admin page."""
    readings = [r for r in database.latest_readings(30) if r.source == ReadingSource.PHYSICAL]
    latest = readings[0] if readings else None
    reference = serial_bridge.reference_distance_cm
    return {
        "manual": not serial_bridge.holding(),
        "reference_distance_cm": reference,
        "latest": None if latest is None else {
            "timestamp": latest.timestamp,
            "level_cm": latest.water_level_cm,
            "distance_cm": round(reference - latest.water_level_cm, 2),
            "quality": latest.quality,
        },
    }


@sensor_router.post("/calibrate")
async def calibrate_zero() -> dict:
    """Make the surface the sensor sees right now read as 0 cm (manual mode, still water)."""
    if serial_bridge.holding():
        raise HTTPException(status_code=409, detail="Switch to manual mode first.")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CALIBRATION_WINDOW_S)
    reference = serial_bridge.reference_distance_cm
    distances = [
        reference - r.water_level_cm
        for r in database.latest_readings(120)
        if r.source == ReadingSource.PHYSICAL and r.quality >= 0.95 and r.timestamp >= cutoff
    ]
    if len(distances) < CALIBRATION_MIN_READINGS:
        raise HTTPException(
            status_code=409,
            detail=f"Need {CALIBRATION_MIN_READINGS} good sensor readings from the last "
            f"{CALIBRATION_WINDOW_S} s; got {len(distances)}. Check the sensor sees the water.",
        )
    new_reference = round(median(distances), 1)
    serial_bridge.reference_distance_cm = new_reference
    _persist_reference(new_reference)
    event_service.reset_live_state()  # start a fresh window at the new zero
    await connections.broadcast({"type": "view", **_view_payload()})
    return {
        "reference_distance_cm": new_reference,
        "samples": len(distances),
        "spread_cm": round(max(distances) - min(distances), 2),
    }


# Dashboard view shared by every open dashboard: "sensor_only" plots just the raw
# readings of the physical sensor (distance from sensor, no other nodes).
_view = {"sensor_only": False}


def _view_payload() -> dict:
    return {**_view, "reference_distance_cm": serial_bridge.reference_distance_cm}


@view_router.get("")
def dashboard_view() -> dict:
    return _view_payload()


@view_router.put("")
async def set_dashboard_view(sensor_only: bool = Query(...)) -> dict:
    _view["sensor_only"] = sensor_only
    payload = _view_payload()
    await connections.broadcast({"type": "view", **payload})
    return payload
