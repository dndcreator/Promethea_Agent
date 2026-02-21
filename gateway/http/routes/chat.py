from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from gateway.protocol import RequestType

from ..dispatcher import dispatch_gateway_method
from ..schemas import ChatRequest, ChatResponse, ConfirmToolRequest
from .auth import get_current_user_id


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user_id)):
    try:
        payload = await dispatch_gateway_method(
            RequestType.CHAT,
            {
                "message": request.message,
                "session_id": request.session_id,
                "stream": request.stream,
            },
            user_id=user_id,
        )
        return ChatResponse(
            response=payload.get("response", ""),
            session_id=payload.get("session_id"),
            status=payload.get("status", "success"),
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            args=payload.get("args"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")


@router.post("/chat/confirm", response_model=ChatResponse)
async def confirm_tool(request: ConfirmToolRequest, user_id: str = Depends(get_current_user_id)):
    try:
        payload = await dispatch_gateway_method(
            RequestType.CHAT_CONFIRM,
            {
                "session_id": request.session_id,
                "tool_call_id": request.tool_call_id,
                "action": request.action,
            },
            user_id=user_id,
        )
        return ChatResponse(
            response=payload.get("response", ""),
            session_id=payload.get("session_id"),
            status=payload.get("status", "success"),
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            args=payload.get("args"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat confirm failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat confirm failed: {e}")


