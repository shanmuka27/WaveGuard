from fastapi import APIRouter

from backend.runtime import event_service
from backend.schemas import NodeStatus

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("", response_model=list[NodeStatus])
def list_nodes() -> list[NodeStatus]:
    return event_service.nodes()
