from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional, Tuple

from backend.database import Database
from backend.detection.event_classifier import classify_node
from backend.detection.node_correlator import correlate
from backend.schemas import Event, EventClassification, NodeStatus, Reading, Severity


class EventService:
    def __init__(self, database: Database, window_size: int = 24) -> None:
        self.database = database
        self.histories: dict[str, deque[Reading]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        self.latest_by_node: dict[str, Reading] = {}
        self.severity_by_node: dict[str, Severity] = {}
        self.current_event: Optional[Event] = None
        self._last_event_signature: Optional[Tuple[str, Tuple[str, ...], str]] = None
        self._last_event_time: Optional[datetime] = None

    def reset_live_state(self) -> None:
        self.histories.clear()
        self.latest_by_node.clear()
        self.severity_by_node.clear()
        self.current_event = None
        self._last_event_signature = None
        self._last_event_time = None

    def reset_node_signals(self, node_ids: list[str]) -> None:
        """Start fresh signal windows for simulated neighbors without losing the real node."""
        for node_id in node_ids:
            self.histories[node_id].clear()
            self.severity_by_node.pop(node_id, None)

    def ingest(self, reading: Reading, detect: bool = True) -> Optional[Event]:
        self.database.save_reading(reading)
        previous = self.latest_by_node.get(reading.node_id)
        if previous is not None and previous.source != reading.source:
            # A real sensor replacing a simulated feed must start a fresh signal window.
            self.histories[reading.node_id].clear()
            self.severity_by_node.pop(reading.node_id, None)
        self.histories[reading.node_id].append(reading)
        self.latest_by_node[reading.node_id] = reading
        return self.detect_event() if detect else None

    def detect_event(self) -> Optional[Event]:
        assessments = [
            classify_node(list(history))
            for history in self.histories.values()
            if len(history) >= 2
        ]
        for assessment in assessments:
            self.severity_by_node[assessment.node_id] = assessment.severity

        event = correlate(
            assessments,
            {node_id: list(history) for node_id, history in self.histories.items()},
        )
        if event is None:
            self.current_event = None
            return None

        signature = (
            event.classification.value,
            tuple(sorted(event.affected_nodes)),
            event.severity.value,
        )
        now = datetime.now(timezone.utc)
        is_duplicate = (
            signature == self._last_event_signature
            and self._last_event_time is not None
            and (now - self._last_event_time).total_seconds() < 5
        )
        if is_duplicate:
            return None

        self.current_event = event
        self._last_event_signature = signature
        self._last_event_time = now
        evidence = [reading for history in self.histories.values() for reading in history]
        self.database.save_event_with_readings(event, evidence)
        return event

    def overall_severity(self) -> Severity:
        severities = list(self.severity_by_node.values())
        if self.current_event is not None:
            severities.append(self.current_event.severity)
        rank = {Severity.SAFE: 0, Severity.WATCH: 1, Severity.WARNING: 2}
        return max(severities, key=rank.__getitem__, default=Severity.SAFE)

    def alert_for(
        self, node_id: Optional[str]
    ) -> Tuple[Severity, Optional[EventClassification]]:
        """Severity and event kind a location's alert board shows; None = whole network.

        A location's own reading severity is raised to the current event's severity
        when the event includes it, so a surge at Holland leaves Ludington's board safe.
        """
        event = self.current_event
        if node_id is None:
            return self.overall_severity(), event.classification if event else None
        severity = self.severity_by_node.get(node_id, Severity.SAFE)
        if event is None or node_id not in event.affected_nodes:
            return severity, None
        rank = {Severity.SAFE: 0, Severity.WATCH: 1, Severity.WARNING: 2}
        return max(severity, event.severity, key=rank.__getitem__), event.classification

    def nodes(self) -> list[NodeStatus]:
        return [
            NodeStatus(
                node_id=node_id,
                source=reading.source,
                severity=self.severity_by_node.get(node_id, Severity.SAFE),
                last_reading=reading,
            )
            for node_id, reading in sorted(self.latest_by_node.items())
        ]
