from dataclasses import dataclass

from backend.detection.signal_features import SignalFeatures, extract_features
from backend.schemas import EventClassification, Reading, Severity


@dataclass(frozen=True)
class NodeAssessment:
    node_id: str
    classification: EventClassification
    severity: Severity
    confidence: float
    features: SignalFeatures


def classify_node(readings: list[Reading]) -> NodeAssessment:
    if not readings:
        raise ValueError("At least one reading is required")

    features = extract_features(readings)
    quality = sum(reading.quality for reading in readings) / len(readings)
    node_id = readings[-1].node_id

    if quality < 0.5:
        return NodeAssessment(
            node_id, EventClassification.SENSOR_FAULT, Severity.WATCH, 1.0 - quality, features
        )

    if len(readings) < 6 or (
        features.amplitude_cm < 1.5 and features.max_rate_cm_per_second < 0.8
    ):
        return NodeAssessment(
            node_id, EventClassification.NORMAL, Severity.SAFE, 0.9, features
        )

    if features.amplitude_cm >= 2.0 and features.direction_changes >= 2:
        confidence = min(0.99, 0.55 + features.amplitude_cm / 12.0)
        return NodeAssessment(
            node_id, EventClassification.SEICHE_LIKE, Severity.WATCH, confidence, features
        )

    if features.max_rate_cm_per_second >= 1.2 and abs(features.trend_cm) >= 3.0:
        confidence = min(0.99, 0.55 + features.max_rate_cm_per_second / 5.0)
        severity = Severity.WARNING if features.amplitude_cm >= 5.0 else Severity.WATCH
        return NodeAssessment(
            node_id, EventClassification.SUDDEN_SURGE, severity, confidence, features
        )

    return NodeAssessment(
        node_id, EventClassification.LOCAL_DISTURBANCE, Severity.WATCH, 0.6, features
    )
