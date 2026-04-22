from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dispatcher import dispatch_gateway_method
from ..dispatcher import get_gateway_server
from gateway.protocol import RequestType
from .auth import get_current_user_id


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/sessions")
async def list_sessions(
    q: str = "",
    pinned_only: bool = False,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
):
    try:
        payload = await dispatch_gateway_method(
            RequestType.SESSIONS_LIST,
            {"q": q, "pinned_only": bool(pinned_only), "limit": max(1, min(int(limit), 1000))},
            user_id=user_id,
        )
        return {"status": "success", **payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}")


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        payload = await dispatch_gateway_method(
            RequestType.SESSION_DETAIL,
            {"session_id": session_id},
            user_id=user_id,
        )
        return {"status": "success", **payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session detail: {e}")


class SessionPinRequest(BaseModel):
    pinned: bool


@router.post("/sessions/{session_id}/pin")
async def set_session_pin(
    session_id: str,
    request: SessionPinRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        gateway_server = get_gateway_server()
        message_manager = getattr(gateway_server, "message_manager", None)
        if message_manager is None or not hasattr(message_manager, "set_session_pinned"):
            raise HTTPException(status_code=503, detail="Message manager not initialized")
        ok = bool(
            message_manager.set_session_pinned(
                session_id=session_id,
                user_id=user_id,
                pinned=bool(request.pinned),
            )
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "status": "success",
            "session_id": session_id,
            "pinned": bool(request.pinned),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update session pin: {e}")


