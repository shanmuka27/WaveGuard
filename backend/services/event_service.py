from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional, Tuple

from backend.database import Database
from backend.detection.event_classifier import classify_node
from backend.detection.node_correlator import correlate
from backend.schemas import Event, NodeStatus, Reading, Severity


class EventService:
    def __init__(self, database: Database, window_size: int = 24) -> None:
        self.database = database
        self.histories: dict[str, deque[Reading]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        self.latest_by_node: dict[str, Reading] = {}
        self.severity_by_node: dict[str, Severity] = {}
        self._last_event_signature: Optional[Tuple[str, Tuple[str, ...], str]] = None
        self._last_event_time: Optional[datetime] = None

    def reset_live_state(self) -> None:
        self.histories.clear()
        self.latest_by_node.clear()
        self.severity_by_node.clear()
        self._last_event_signature = None
        self._last_event_time = None

    def ingest(self, reading: Reading, detect: bool = True) -> Optional[Event]:
        self.database.save_reading(reading)
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

        self._last_event_signature = signature
        self._last_event_time = now
        self.database.save_event(event)
        return event

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
