from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Optional
from uuid import uuid4

from backend.detection.event_classifier import NodeAssessment
from backend.schemas import Event, EventClassification, Reading, Severity


def _pearson(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size < 3:
        return 0.0
    left = left[-size:]
    right = right[-size:]
    left_mean = sum(left) / size
    right_mean = sum(right) / size
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else 0.0


def correlate(
    assessments: list[NodeAssessment], histories: dict[str, list[Reading]]
) -> Optional[Event]:
    abnormal = [
        assessment
        for assessment in assessments
        if assessment.classification != EventClassification.NORMAL
    ]
    if not abnormal:
        return None

    affected_nodes = [assessment.node_id for assessment in abnormal]
    correlations: list[float] = []
    for index, left_node in enumerate(affected_nodes):
        for right_node in affected_nodes[index + 1 :]:
            left = [reading.water_level_cm for reading in histories[left_node]]
            right = [reading.water_level_cm for reading in histories[right_node]]
            correlations.append(max(0.0, _pearson(left, right)))
    correlation_score = sum(correlations) / len(correlations) if correlations else 0.0

    if len(abnormal) == 1:
        classification = abnormal[0].classification
        if classification not in (EventClassification.SENSOR_FAULT,):
            classification = EventClassification.LOCAL_DISTURBANCE
        severity = Severity.WATCH
    else:
        classifications = [assessment.classification for assessment in abnormal]
        classification = Counter(classifications).most_common(1)[0][0]
        if correlation_score < 0.45:
            classification = EventClassification.LOCAL_DISTURBANCE
        severity = (
            Severity.WARNING
            if len(abnormal) >= 3 and correlation_score >= 0.7
            else Severity.WATCH
        )

    confidence = sum(assessment.confidence for assessment in abnormal) / len(abnormal)
    amplitude = max(assessment.features.amplitude_cm for assessment in abnormal)
    periods = [
        assessment.features.estimated_period_seconds
        for assessment in abnormal
        if assessment.features.estimated_period_seconds is not None
    ]

    return Event(
        event_id=f"evt-{uuid4().hex[:10]}",
        classification=classification,
        severity=severity,
        confidence=round(confidence, 3),
        affected_nodes=affected_nodes,
        amplitude_cm=round(amplitude, 3),
        period_seconds=round(sum(periods) / len(periods), 3) if periods else None,
        correlation_score=round(correlation_score, 3),
    )
