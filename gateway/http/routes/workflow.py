from __future__ import annotations

from fastapi import APIRouter, Depends

from gateway.protocol import RequestType

from ..dispatcher import dispatch_gateway_method
from .auth import get_current_user_id


router = APIRouter()


@router.post("/workflow/define")
async def define_workflow(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    body = dict(payload or {})
    body.setdefault("owner_user_id", user_id)
    data = await dispatch_gateway_method(RequestType.WORKFLOW_DEFINE, body, user_id=user_id)
    return {"status": "success", **data}


@router.get("/workflow/list")
async def list_workflows(
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(
        RequestType.WORKFLOW_LIST,
        {"owner_user_id": user_id, "limit": limit},
        user_id=user_id,
    )
    return {"status": "success", **data}


@router.post("/workflow/start")
async def start_workflow(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(RequestType.WORKFLOW_START, payload or {}, user_id=user_id)
    return {"status": "success", **data}


@router.get("/workflow/run/{workflow_run_id}")
async def workflow_status(
    workflow_run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(
        RequestType.WORKFLOW_STATUS,
        {"workflow_run_id": workflow_run_id},
        user_id=user_id,
    )
    return {"status": "success", **data}


@router.post("/workflow/pause/{workflow_run_id}")
async def pause_workflow(
    workflow_run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(
        RequestType.WORKFLOW_PAUSE,
        {"workflow_run_id": workflow_run_id},
        user_id=user_id,
    )
    return {"status": "success", **data}


@router.post("/workflow/resume/{workflow_run_id}")
async def resume_workflow(
    workflow_run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(
        RequestType.WORKFLOW_RESUME,
        {"workflow_run_id": workflow_run_id},
        user_id=user_id,
    )
    return {"status": "success", **data}


@router.post("/workflow/retry")
async def retry_workflow_step(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(RequestType.WORKFLOW_RETRY_STEP, payload or {}, user_id=user_id)
    return {"status": "success", **data}


@router.post("/workflow/approve")
async def approve_workflow_step(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    body = dict(payload or {})
    body.setdefault("approved_by", user_id)
    data = await dispatch_gateway_method(RequestType.WORKFLOW_APPROVE_STEP, body, user_id=user_id)
    return {"status": "success", **data}


@router.get("/workflow/checkpoints/{workflow_run_id}")
async def workflow_checkpoints(
    workflow_run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    data = await dispatch_gateway_method(
        RequestType.WORKFLOW_CHECKPOINTS,
        {"workflow_run_id": workflow_run_id},
        user_id=user_id,
    )
    return {"status": "success", **data}
