from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

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
    period_seconds: Optional[float] = None
    correlation_score: float = Field(ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NodeStatus(BaseModel):
    node_id: str
    source: ReadingSource
    severity: Severity
    last_reading: Reading


class IngestResult(BaseModel):
    reading: Reading
    event: Optional[Event] = None


class ScenarioResult(BaseModel):
    scenario: str
    location: Optional[str] = None
    source_note: Optional[str] = None
    readings_generated: int
    event: Optional[Event] = None
