from datetime import datetime, timedelta, timezone
from math import pi, sin

from backend.detection.event_classifier import classify_node
from backend.schemas import EventClassification, Reading, ReadingSource


def make_readings(values: list[float], node_id: str = "TEST-01") -> list[Reading]:
    start = datetime(2026, 10, 3, tzinfo=timezone.utc)
    return [
        Reading(
            node_id=node_id,
            timestamp=start + timedelta(seconds=index),
            water_level_cm=value,
            quality=0.98,
            source=ReadingSource.SIMULATED,
        )
        for index, value in enumerate(values)
    ]


def test_normal_signal_stays_normal() -> None:
    assessment = classify_node(make_readings([14.0, 14.1, 14.0, 13.9, 14.0, 14.1]))
    assert assessment.classification == EventClassification.NORMAL


def test_rising_signal_is_sudden_surge() -> None:
    assessment = classify_node(make_readings([14.0, 14.2, 14.4, 15.8, 17.2, 18.6]))
    assert assessment.classification == EventClassification.SUDDEN_SURGE


def test_oscillating_signal_is_seiche_like() -> None:
    values = [14.0 + 3.5 * sin(index * pi / 3) for index in range(12)]
    assessment = classify_node(make_readings(values))
    assert assessment.classification == EventClassification.SEICHE_LIKE
