from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ReadingSource(str, Enum):
    PHYSICAL = "physical"
    SIMULATED = "simulated"


class EventClassification(str, Enum):
    NORMAL = "normal"
    LOCAL_DISTURBANCE = "local_disturbance"
    SEICHE_LIKE = "seiche_like"
    SUDDEN_SURGE = "sudden_surge"
    SENSOR_FAULT = "sensor_fault"


class Severity(str, Enum):
    SAFE = "safe"
    WATCH = "watch"
    WARNING = "warning"


class Reading(BaseModel):
    node_id: str
    timestamp: datetime
    water_level_cm: float
    quality: float = Field(ge=0.0, le=1.0)
    source: ReadingSource


class Event(BaseModel):
    event_id: str
    classification: EventClassification
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    affected_nodes: list[str]
    amplitude_cm: float
    period_seconds: float | None = None
    correlation_score: float = Field(ge=0.0, le=1.0)
