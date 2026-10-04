from dataclasses import dataclass

from backend.detection.signal_features import SignalFeatures, extract_features
from backend.schemas import EventClassification, Reading, Severity

NOISE_BAND_CM = 1.5


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

    # Movement smaller than the noise band is normal however fast it jitters: a real
    # ultrasonic sensor hops ~1 cm between 1 Hz readings even over still water.
    if len(readings) < 6 or features.amplitude_cm < NOISE_BAND_CM:
        return NodeAssessment(
            node_id, EventClassification.NORMAL, Severity.SAFE, 0.9, features
        )

    # A rise that dominates the window is a surge even if real gauge data wiggles
    # on the way up (which would otherwise look like an oscillation).
    if (
        features.max_rate_cm_per_second >= 1.2
        and abs(features.trend_cm) >= 3.0
        and abs(features.trend_cm) >= 0.6 * features.amplitude_cm
    ):
        confidence = min(0.99, 0.55 + features.max_rate_cm_per_second / 5.0)
        severity = Severity.WARNING if features.amplitude_cm >= 5.0 else Severity.WATCH
        return NodeAssessment(
            node_id, EventClassification.SUDDEN_SURGE, severity, confidence, features
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
