from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..dispatcher import dispatch_gateway_method
from gateway.protocol import RequestType
from .auth import get_current_user_id


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    try:
        payload = await dispatch_gateway_method(
            RequestType.SESSIONS_LIST,
            {},
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


