from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from gateway.protocol import RequestType

from ..dispatcher import dispatch_gateway_method


router = APIRouter()


class AutomationTriggerRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None
    source: str = "webhook"


class SchedulerRunOnceRequest(BaseModel):
    max_jobs: int = 10


def _enforce_automation_token(token: Optional[str]) -> None:
    expected = (os.getenv("AUTOMATION__TOKEN") or "").strip()
    if not expected:
        return
    if not token or token.strip() != expected:
        raise HTTPException(status_code=403, detail="invalid automation token")


@router.post("/automation/webhook")
async def trigger_webhook(
    request: AutomationTriggerRequest,
    raw_request: Request,
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
        request=raw_request,
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
    raw_request: Request,
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
        request=raw_request,
    )
    return {
        "status": "success",
        "trigger": "cron_wakeup",
        "source": request.source,
        "user_id": request.user_id,
        **payload,
    }


@router.get("/automation/scheduler/status")
async def get_scheduler_status():
    from .. import state

    scheduler = getattr(state, "kernel_scheduler", None)
    if not scheduler:
        return {
            "status": "unavailable",
            "scheduler": {
                "enabled": False,
                "running": False,
                "paused": True,
                "tick_seconds": None,
                "max_jobs_per_tick": None,
                "total_ticks": 0,
                "total_jobs_run": 0,
            },
        }
    return {"status": "success", "scheduler": scheduler.get_status()}


@router.post("/automation/scheduler/run-once")
async def run_scheduler_once(
    request: SchedulerRunOnceRequest,
    x_automation_token: Optional[str] = Header(default=None),
):
    from .. import state

    _enforce_automation_token(x_automation_token)
    scheduler = getattr(state, "kernel_scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="kernel scheduler not initialized")
    out = await scheduler.run_once(max_jobs=max(1, int(request.max_jobs)))
    return {"status": "success", "result": out, "scheduler": scheduler.get_status()}


@router.post("/automation/scheduler/pause")
async def pause_scheduler(x_automation_token: Optional[str] = Header(default=None)):
    from .. import state

    _enforce_automation_token(x_automation_token)
    scheduler = getattr(state, "kernel_scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="kernel scheduler not initialized")
    await scheduler.pause()
    return {"status": "success", "scheduler": scheduler.get_status()}


@router.post("/automation/scheduler/resume")
async def resume_scheduler(x_automation_token: Optional[str] = Header(default=None)):
    from .. import state

    _enforce_automation_token(x_automation_token)
    scheduler = getattr(state, "kernel_scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="kernel scheduler not initialized")
    await scheduler.resume()
    return {"status": "success", "scheduler": scheduler.get_status()}
