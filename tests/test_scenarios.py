from datetime import datetime, timedelta, timezone

from backend.detection.event_classifier import classify_node
from backend.detection.node_correlator import correlate
from backend.routes.scenarios import NODES, SEED_STEPS, nearest_nodes, playback, source_note
from backend.schemas import EventClassification, Reading, Severity


def detect(scenario: str, location=None):
    """The detector's verdict on the readings seeded when a scenario starts."""
    levels = playback(scenario, location)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    histories = {
        node_id: [
            Reading(
                node_id=node_id,
                timestamp=start + timedelta(seconds=step),
                water_level_cm=levels[node_id][step],
                quality=0.98,
                source=source,
            )
            for step in range(SEED_STEPS)
        ]
        for node_id, source in NODES
    }
    return correlate([classify_node(h) for h in histories.values()], histories)


def test_nearest_neighbours_follow_the_shoreline():
    assert nearest_nodes("HOLLAND-03", 2) == ["GRANDHAVEN-04", "SOUTHHAVEN-05"]
    assert nearest_nodes("MANISTEE-06", 1) == ["LUDINGTON-01"]


def test_localized_surge_warns_only_that_stretch_of_shore():
    event = detect("sudden_surge", "HOLLAND-03")
    assert event.classification == EventClassification.SUDDEN_SURGE
    assert event.severity == Severity.WARNING
    assert sorted(event.affected_nodes) == ["GRANDHAVEN-04", "HOLLAND-03", "SOUTHHAVEN-05"]


def test_localized_seiche_warns_only_that_stretch_of_shore():
    event = detect("seiche", "LUDINGTON-01")
    assert event.severity == Severity.WARNING
    assert sorted(event.affected_nodes) == ["LUDINGTON-01", "MANISTEE-06", "MUSKEGON-02"]


def test_local_disturbance_stays_at_the_chosen_location():
    event = detect("local_disturbance", "SOUTHHAVEN-05")
    assert event.classification == EventClassification.LOCAL_DISTURBANCE
    assert event.severity == Severity.WATCH
    assert event.affected_nodes == ["SOUTHHAVEN-05"]


def test_whole_shoreline_seiche_still_reaches_every_node():
    event = detect("seiche")
    assert event.severity == Severity.WARNING
    assert len(event.affected_nodes) == len(NODES)


def test_normal_produces_no_event_anywhere():
    assert detect("normal", "MUSKEGON-02") is None


def test_physical_station_scenario_stays_within_the_sensor_reach():
    from backend.config import settings
    from backend.routes.scenarios import SENSOR_BLIND_SPOT_CM

    levels = playback("sudden_surge", "LUDINGTON-01")["LUDINGTON-01"]
    assert max(levels) <= settings.reference_distance_cm - SENSOR_BLIND_SPOT_CM


def test_replays_disclose_their_source():
    assert "NOAA" in source_note("seiche", "HOLLAND-03")
    assert "synthetic" in source_note("sudden_surge", "HOLLAND-03")
    assert "synthetic" in source_note("local_disturbance", "HOLLAND-03")


def test_manual_mode_plays_calm_records_for_every_other_node():
    from backend.routes.scenarios import PHYSICAL_NODE

    assert detect("manual", "LUDINGTON-01") is None
    assert "live tray sensor" in source_note("manual", "LUDINGTON-01")
    levels = playback("manual", "LUDINGTON-01")
    assert all(max(abs(v) for v in series) < 1.5 for node, series in levels.items() if node != PHYSICAL_NODE)


def test_scenarios_keep_playing_until_switched():
    from backend.routes.scenarios import SURGE_LOOP_START, _loop_index
    from backend.services.replay import replay_length

    length = replay_length()
    assert _loop_index("seiche", length) == SEED_STEPS
    assert _loop_index("seiche", length + 5) == SEED_STEPS + 5
    # a surge keeps cycling its high-water plateau, never the rise again
    assert all(_loop_index("sudden_surge", step) >= SURGE_LOOP_START for step in range(length, length + 200))
