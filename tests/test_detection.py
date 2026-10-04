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


def test_sensor_jitter_within_noise_band_stays_normal() -> None:
    # Recorded from the physical HC-SR04 over a still surface: ~1 cm hops at 1 Hz.
    values = [1.1, 1.1, 1.5, 1.5, 1.1, 1.1, 1.7, 1.7, 0.7, 1.5, 0.7, 1.5]
    assessment = classify_node(make_readings(values))
    assert assessment.classification == EventClassification.NORMAL


def test_rising_signal_is_sudden_surge() -> None:
    assessment = classify_node(make_readings([14.0, 14.2, 14.4, 15.8, 17.2, 18.6]))
    assert assessment.classification == EventClassification.SUDDEN_SURGE


def test_oscillating_signal_is_seiche_like() -> None:
    values = [14.0 + 3.5 * sin(index * pi / 3) for index in range(12)]
    assessment = classify_node(make_readings(values))
    assert assessment.classification == EventClassification.SEICHE_LIKE


def test_batched_writes_save_every_reading_once_flushed(tmp_path) -> None:
    from backend.database import Database
    from backend.services.event_service import EventService

    database = Database(str(tmp_path / "batched.db"))
    database.initialize()
    service = EventService(database, batch_writes=True)
    for reading in make_readings([14.0 + i * 0.1 for i in range(30)]):
        service.ingest(reading, detect=False)

    service.flush_readings()

    assert len(database.latest_readings(100)) == 30


def test_raised_alert_holds_through_a_brief_dip(tmp_path) -> None:
    from backend.database import Database
    from backend.services.event_service import EventService
    from backend.schemas import Severity

    database = Database(str(tmp_path / "hold.db"))
    database.initialize()
    service = EventService(database)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    oscillating = [3.5 * sin(index * pi / 3) for index in range(12)]
    for node in ("A-01", "B-02", "C-03"):
        for index, value in enumerate(oscillating):
            service.ingest(Reading(node_id=node, timestamp=start + timedelta(seconds=index),
                                   water_level_cm=value, quality=0.98,
                                   source=ReadingSource.SIMULATED), detect=False)
    assert service.detect_event().severity == Severity.WARNING

    # One node calms: correlation now only supports a watch, but the warning holds.
    for index in range(12, 36):
        service.ingest(Reading(node_id="C-03", timestamp=start + timedelta(seconds=index),
                               water_level_cm=0.0, quality=0.98,
                               source=ReadingSource.SIMULATED), detect=False)
    service.detect_event()
    assert service.overall_severity() == Severity.WARNING

    service.reset_live_state()  # a new scenario clears it at once
    assert service.overall_severity() == Severity.SAFE
