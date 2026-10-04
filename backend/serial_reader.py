from datetime import datetime, timezone

from typing import Optional

from backend.schemas import EventClassification, Reading, ReadingSource, Severity


def parse_reading_line(
    line: str, node_id: str, reference_distance_cm: float
) -> Reading:
    """Parse READING,<unix timestamp>,<distance cm>,<quality>."""
    parts = [part.strip() for part in line.strip().split(",")]
    if len(parts) != 4 or parts[0] != "READING":
        raise ValueError("Expected READING,<timestamp>,<distance_cm>,<quality>")

    timestamp = datetime.fromtimestamp(float(parts[1]), tz=timezone.utc)
    distance_cm = float(parts[2])
    quality = float(parts[3])
    return Reading(
        node_id=node_id,
        timestamp=timestamp,
        water_level_cm=reference_distance_cm - distance_cm,
        quality=quality,
        source=ReadingSource.PHYSICAL,
    )


def state_command(
    severity: Severity, classification: Optional[EventClassification] = None
) -> str:
    """Alert command for the Arduino. A sudden-surge warning flashes red (SURGE)."""
    if severity == Severity.WARNING and classification == EventClassification.SUDDEN_SURGE:
        return "STATE,SURGE\n"
    return f"STATE,{severity.value.upper()}\n"
