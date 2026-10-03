"""IBM Granite explanation endpoints and watsonx Orchestrate tool operations.

Register in backend/main.py with:

    from backend.routes import agent_tools
    app.include_router(agent_tools.router)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.runtime import database, event_service
from backend.schemas import Event, NodeStatus, Severity
from backend.services.watsonx_client import (
    ExplanationResult,
    WatsonxError,
    get_client,
    load_prerecorded,
)

router = APIRouter(tags=["ibm"])

SEVERITY_RANK = {Severity.SAFE: 0, Severity.WATCH: 1, Severity.WARNING: 2}
ERROR_STATUS = {"not_configured": 503, "auth_failed": 502, "timeout": 504}


class IbmStatus(BaseModel):
    configured: bool
    model_id: str
    last_error: Optional[str] = None


class SituationReport(BaseModel):
    overall_severity: Severity
    nodes: list[NodeStatus]
    latest_event: Optional[Event] = None
    summary: str


def _node_sources() -> dict[str, str]:
    return {node.node_id: node.source.value for node in event_service.nodes()}


def _require_event(event_id: str) -> Event:
    event = database.event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/api/ibm/status", response_model=IbmStatus)
def ibm_status() -> IbmStatus:
    return IbmStatus(**get_client().status())


@router.post(
    "/api/events/{event_id}/explain",
    response_model=ExplanationResult,
    operation_id="explainEvent",
    summary="Explain a stored hazard event with IBM Granite",
)
def explain_event(
    event_id: str, refresh: bool = Query(default=False)
) -> ExplanationResult:
    event = _require_event(event_id)
    try:
        return get_client().explain(event, _node_sources(), refresh=refresh)
    except WatsonxError as error:
        raise HTTPException(
            status_code=ERROR_STATUS.get(error.code, 502),
            detail={"code": error.code, "message": error.message},
        ) from error


@router.get(
    "/api/ibm/example",
    response_model=ExplanationResult,
    summary="Saved Granite response, labeled prerecorded, for when IBM is unavailable",
)
def prerecorded_example(event_id: Optional[str] = None) -> ExplanationResult:
    return load_prerecorded(database.event(event_id) if event_id else None)


@router.get(
    "/api/agent/situation",
    response_model=SituationReport,
    operation_id="getSituationReport",
    summary="Current network severity, node states, and the active hazard event, if any",
)
def situation_report() -> SituationReport:
    nodes = event_service.nodes()
    events = database.events(1)
    latest = events[0] if events else None

    # A stored event only counts while at least one of its nodes is still abnormal,
    # so an old warning does not outlive a later normal scenario.
    if latest and not any(
        node.node_id in latest.affected_nodes and node.severity != Severity.SAFE
        for node in nodes
    ):
        latest = None
    severities = [node.severity for node in nodes]
    if latest:
        severities.append(latest.severity)
    overall = max(severities, key=SEVERITY_RANK.__getitem__, default=Severity.SAFE)

    if not nodes:
        summary = "No shoreline nodes have reported readings yet."
    elif overall == Severity.SAFE:
        summary = f"All {len(nodes)} reporting nodes are safe."
    else:
        affected = ", ".join(latest.affected_nodes) if latest else "unknown nodes"
        kind = latest.classification.value if latest else "abnormal behavior"
        summary = f"Network severity is {overall.value}: {kind} affecting {affected}."
    return SituationReport(
        overall_severity=overall, nodes=nodes, latest_event=latest, summary=summary
    )
