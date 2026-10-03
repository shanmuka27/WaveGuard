from datetime import datetime, timedelta, timezone
from math import pi, sin

from backend.detection.event_classifier import classify_node
from backend.detection.node_correlator import correlate
from backend.schemas import Reading, ReadingSource, Severity


def history(node_id: str, offset: float) -> list[Reading]:
    start = datetime(2026, 10, 3, tzinfo=timezone.utc)
    return [
        Reading(
            node_id=node_id,
            timestamp=start + timedelta(seconds=index),
            water_level_cm=14.0 + offset + 3.5 * sin(index * pi / 3),
            quality=0.98,
            source=ReadingSource.SIMULATED,
        )
        for index in range(12)
    ]


def test_three_correlated_nodes_create_warning() -> None:
    histories = {
        "NODE-01": history("NODE-01", 0.0),
        "NODE-02": history("NODE-02", 0.3),
        "NODE-03": history("NODE-03", 0.6),
    }
    event = correlate(
        [classify_node(readings) for readings in histories.values()], histories
    )
    assert event is not None
    assert event.severity == Severity.WARNING
    assert event.correlation_score >= 0.99
