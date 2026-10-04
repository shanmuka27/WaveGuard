"""Real NOAA gauge records replayed for the demo scenarios.

Only two NOAA CO-OPS water-level gauges sit on this shore: Ludington (9087023) and
Holland (9087031). Each simulated node replays the record of its nearest gauge:
a real 2024 seiche, or a calm real day. NOAA's 6-minute readings average away how
sudden a surge is (real surges replay as oscillations), so surges stay synthetic. Records are time-compressed (one
6-minute reading per replayed second) and rescaled to the demo tray's size so they
share one scale with the physical sensor and the detector's thresholds.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "noaa_replay.json"

GAUGES = {"9087023": "Ludington", "9087031": "Holland"}
GAUGE_FOR_NODE = {
    "MANISTEE-06": "9087023",
    "LUDINGTON-01": "9087023",
    "MUSKEGON-02": "9087031",
    "GRANDHAVEN-04": "9087031",
    "HOLLAND-03": "9087031",
    "SOUTHHAVEN-05": "9087031",
}

# Peak-to-trough size each replayed event is rescaled to, in demo-tray cm. Both
# gauges share one factor, so their relative sizes stay as recorded.
TARGET_RANGE_CM = {"seiche": 4.5}
CALM_SCALE = 0.3  # a calm real day, shrunk to tray size the same way
SMOOTHING_READINGS = 3  # centered moving average that removes chop, keeps the event shape


def _smoothed(values: list[float]) -> list[float]:
    half = SMOOTHING_READINGS // 2
    return [
        sum(values[max(0, i - half): i + half + 1]) / len(values[max(0, i - half): i + half + 1])
        for i in range(len(values))
    ]


@lru_cache(maxsize=1)
def records() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def replay_length() -> int:
    return len(records()["normal"]["gauges"]["9087023"])


def gauge_series(kind: str, node_id: str) -> list[float]:
    """Demo-scale replay of the node's nearest gauge for the 'normal' or 'seiche' record."""
    record = records()[kind]
    values = _smoothed(record["gauges"][GAUGE_FOR_NODE[node_id]])
    if kind == "normal":
        return [value * CALM_SCALE for value in values]
    gauges = [_smoothed(series) for series in record["gauges"].values()]
    span = max(max(series) - min(series) for series in gauges)
    scale = TARGET_RANGE_CM[kind] / span
    return [value * scale for value in values]


def describe(kind: Optional[str]) -> Optional[str]:
    """One-line disclosure of what a replay shows, for the dashboard."""
    if kind not in records():
        return None
    record = records()[kind]
    return (
        f"Replaying NOAA gauges Ludington 9087023 and Holland 9087031 from {record['start']} UTC "
        "(6-minute readings shown each second, smoothed and rescaled to tray size)"
    )
