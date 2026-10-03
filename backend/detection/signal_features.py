from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev
from typing import Optional

from backend.schemas import Reading


@dataclass(frozen=True)
class SignalFeatures:
    amplitude_cm: float
    max_rate_cm_per_second: float
    standard_deviation_cm: float
    direction_changes: int
    trend_cm: float
    estimated_period_seconds: Optional[float]


def extract_features(readings: list[Reading]) -> SignalFeatures:
    if len(readings) < 2:
        return SignalFeatures(0.0, 0.0, 0.0, 0, 0.0, None)

    ordered = sorted(readings, key=lambda reading: reading.timestamp)
    values = [reading.water_level_cm for reading in ordered]
    deltas: list[float] = []
    rates: list[float] = []

    for previous, current in zip(ordered, ordered[1:]):
        delta = current.water_level_cm - previous.water_level_cm
        seconds = max((current.timestamp - previous.timestamp).total_seconds(), 0.001)
        deltas.append(delta)
        rates.append(abs(delta) / seconds)

    signs = [1 if delta > 0 else -1 for delta in deltas if abs(delta) >= 0.05]
    direction_changes = sum(a != b for a, b in zip(signs, signs[1:]))

    peaks: list[float] = []
    for index in range(1, len(values) - 1):
        if values[index] > values[index - 1] and values[index] >= values[index + 1]:
            peaks.append(ordered[index].timestamp.timestamp())
    period = None
    if len(peaks) >= 2:
        intervals = [current - previous for previous, current in zip(peaks, peaks[1:])]
        period = sum(intervals) / len(intervals)

    return SignalFeatures(
        amplitude_cm=max(values) - min(values),
        max_rate_cm_per_second=max(rates, default=0.0),
        standard_deviation_cm=pstdev(values),
        direction_changes=direction_changes,
        trend_cm=values[-1] - values[0],
        estimated_period_seconds=period,
    )
