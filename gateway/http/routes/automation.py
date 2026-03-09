from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from gateway.protocol import RequestType

from ..dispatcher import dispatch_gateway_method


router = APIRouter()


class AutomationTriggerRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None
    source: str = "webhook"


def _enforce_automation_token(token: Optional[str]) -> None:
    expected = (os.getenv("AUTOMATION__TOKEN") or "").strip()
    if not expected:
        return
    if not token or token.strip() != expected:
        raise HTTPException(status_code=403, detail="invalid automation token")


@router.post("/automation/webhook")
async def trigger_webhook(
    request: AutomationTriggerRequest,
    x_automation_token: Optional[str] = Header(default=None),
):
    _enforce_automation_token(x_automation_token)
    payload = await dispatch_gateway_method(
        RequestType.CHAT,
        {
            "message": request.message,
            "session_id": request.session_id,
            "stream": False,
        },
        user_id=request.user_id,
    )
    return {
        "status": "success",
        "trigger": "webhook",
        "source": request.source,
        "user_id": request.user_id,
        **payload,
    }


@router.post("/automation/cron/wakeup")
async def trigger_cron_wakeup(
    request: AutomationTriggerRequest,
    x_automation_token: Optional[str] = Header(default=None),
):
    _enforce_automation_token(x_automation_token)
    content = request.message.strip() or "Daily wakeup check"
    payload = await dispatch_gateway_method(
        RequestType.CHAT,
        {
            "message": content,
            "session_id": request.session_id,
            "stream": False,
        },
        user_id=request.user_id,
    )
    return {
        "status": "success",
        "trigger": "cron_wakeup",
        "source": request.source,
        "user_id": request.user_id,
        **payload,
    }
