from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..dispatcher import get_gateway_server
from .auth import get_current_user_id


router = APIRouter(prefix="/reasoning", tags=["reasoning"])


class ReasoningStopRequest(BaseModel):
    reason: Optional[str] = None


class ReasoningSteerRequest(BaseModel):
    note: str


@router.get("/active")
async def list_active_reasoning_trees(
    session_id: Optional[str] = Query(default=None),
    include_pending: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    gateway_server = get_gateway_server()
    service = getattr(gateway_server, "reasoning_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Reasoning service not initialized")
    return service.list_runtime_trees(
        user_id=user_id,
        session_id=session_id,
        include_pending=bool(include_pending),
        limit=limit,
    )


@router.get("/tree/{tree_id}")
async def get_reasoning_tree(
    tree_id: str,
    include_nodes: bool = Query(default=True),
    user_id: str = Depends(get_current_user_id),
):
    gateway_server = get_gateway_server()
    service = getattr(gateway_server, "reasoning_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Reasoning service not initialized")
    payload = service.get_runtime_tree(
        tree_id=tree_id,
        user_id=user_id,
        include_nodes=bool(include_nodes),
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Reasoning tree not found")
    return payload


@router.post("/tree/{tree_id}/stop")
async def stop_reasoning_tree(
    tree_id: str,
    request: ReasoningStopRequest,
    user_id: str = Depends(get_current_user_id),
):
    gateway_server = get_gateway_server()
    service = getattr(gateway_server, "reasoning_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Reasoning service not initialized")
    result = service.request_stop(
        tree_id=tree_id,
        user_id=user_id,
        reason=request.reason or "",
    )
    status = result.get("status")
    if status == "missing":
        raise HTTPException(status_code=404, detail="Reasoning tree not found")
    if status == "forbidden":
        raise HTTPException(status_code=403, detail="Not allowed")
    if status != "accepted":
        raise HTTPException(status_code=400, detail=f"Failed to stop reasoning tree: {status}")
    return result


@router.post("/tree/{tree_id}/steer")
async def steer_reasoning_tree(
    tree_id: str,
    request: ReasoningSteerRequest,
    user_id: str = Depends(get_current_user_id),
):
    gateway_server = get_gateway_server()
    service = getattr(gateway_server, "reasoning_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Reasoning service not initialized")
    result = service.add_steering_note(
        tree_id=tree_id,
        user_id=user_id,
        note=request.note,
    )
    status = result.get("status")
    if status == "missing":
        raise HTTPException(status_code=404, detail="Reasoning tree not found")
    if status == "forbidden":
        raise HTTPException(status_code=403, detail="Not allowed")
    if status == "invalid":
        raise HTTPException(status_code=400, detail="note is required")
    if status != "accepted":
        raise HTTPException(status_code=400, detail=f"Failed to steer reasoning tree: {status}")
    return result

