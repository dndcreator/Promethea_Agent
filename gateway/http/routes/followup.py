from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..dispatcher import dispatch_gateway_method
from gateway.protocol import RequestType
from ..schemas import FollowUpRequest
from .auth import get_current_user_id


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/followup")
async def handle_followup(
    request: FollowUpRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        payload = await dispatch_gateway_method(
            RequestType.FOLLOWUP,
            {
                "selected_text": request.selected_text,
                "query_type": request.query_type,
                "custom_query": request.custom_query,
                "session_id": request.session_id,
            },
            user_id=user_id,
        )
        return {
            "status": "success",
            "response": payload.get("response", ""),
            "query": payload.get("query", ""),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"followup failed: {e}")
        raise HTTPException(status_code=500, detail=f"followup failed: {e}")


