"""Build a reviewable incident timeline from the detector's saved input window."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal, Optional

from pydantic import BaseModel

from backend.schemas import Event, Reading, ReadingSource, Severity

CHANGE_THRESHOLD_CM = 1.0


class ReplayNode(BaseModel):
    node_id: str
    source: ReadingSource
    affected: bool
    first_reading_at: str
    first_changed_at: Optional[str]
    baseline_cm: float
    peak_change_cm: float
    reading_count: int


class IncidentReplay(BaseModel):
    event: Event
    storage: Literal["tiger_data", "sqlite"]
    readings: list[Reading]
    nodes: list[ReplayNode]
    change_threshold_cm: float
    detector_reason: str


def summarize_nodes(event: Event, readings: list[Reading]) -> list[ReplayNode]:
    grouped: dict[str, list[Reading]] = defaultdict(list)
    for reading in readings:
        grouped[reading.node_id].append(reading)
    result = []
    for node_id, history in sorted(grouped.items()):
        history.sort(key=lambda reading: reading.timestamp)
        usable = [reading for reading in history if reading.quality > 0.5]
        baseline = usable[0] if usable else history[0]
        changed = next(
            (reading for reading in usable if abs(reading.water_level_cm - baseline.water_level_cm) >= CHANGE_THRESHOLD_CM),
            None,
        )
        result.append(
            ReplayNode(
                node_id=node_id,
                source=history[-1].source,
                affected=node_id in event.affected_nodes,
                first_reading_at=history[0].timestamp.isoformat(),
                first_changed_at=changed.timestamp.isoformat() if changed else None,
                baseline_cm=baseline.water_level_cm,
                peak_change_cm=round(
                    max((abs(reading.water_level_cm - baseline.water_level_cm) for reading in usable), default=0), 3
                ),
                reading_count=len(history),
            )
        )
    return result


def detector_reason(event: Event) -> str:
    if event.severity == Severity.WARNING:
        return (
            f"Python issued WARNING because {len(event.affected_nodes)} nodes were abnormal "
            f"with correlation {event.correlation_score:.2f}. The warning rule requires "
            "at least 3 abnormal nodes and correlation of at least 0.70. "
            f"Classification: {event.classification.value}; largest amplitude: {event.amplitude_cm:.2f} cm."
        )
    return (
        f"Python issued {event.severity.value.upper()} for {len(event.affected_nodes)} "
        f"abnormal node(s). Classification: {event.classification.value}; "
        f"correlation: {event.correlation_score:.2f}; largest amplitude: {event.amplitude_cm:.2f} cm."
    )


def build_replay(event: Event, readings: list[Reading], storage: Literal["tiger_data", "sqlite"]) -> IncidentReplay:
    ordered = sorted(readings, key=lambda reading: (reading.timestamp, reading.node_id))
    return IncidentReplay(
        event=event,
        storage=storage,
        readings=ordered,
        nodes=summarize_nodes(event, ordered),
        change_threshold_cm=CHANGE_THRESHOLD_CM,
        detector_reason=detector_reason(event),
    )
