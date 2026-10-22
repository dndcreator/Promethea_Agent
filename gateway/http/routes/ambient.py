"""Authenticated presentation/configuration over the Ambient first-level service."""
from fastapi import APIRouter, Depends, HTTPException

from gateway.public_contracts import AmbientConfirmation, AmbientFeedback, AmbientSettings, AmbientState
from gateway.task_service import TaskExecutionConflict
from ..dispatcher import get_gateway_server
from .auth import get_current_user_id


router = APIRouter(prefix="/ambient", tags=["ambient"])


def service():
    result = getattr(get_gateway_server(), "ambient_service", None)
    if result is None:
        raise HTTPException(503, "Ambient Runtime is not initialized")
    return result


def translate(exc):
    code = 409 if isinstance(exc, TaskExecutionConflict) else 404 if isinstance(exc, KeyError) else 403 if isinstance(exc, PermissionError) else 422
    raise HTTPException(code, detail=str(exc)) from exc


@router.get("", response_model=AmbientState)
@router.get("/{session_id}", response_model=AmbientState)
async def get_ambient(session_id: str = None, user_id: str = Depends(get_current_user_id)):
    try:
        return service().view(user_id, session_id)
    except (KeyError, ValueError, PermissionError, TaskExecutionConflict) as exc:
        translate(exc)


@router.put("", response_model=AmbientState)
@router.put("/{session_id}", response_model=AmbientState)
async def set_ambient(body: AmbientSettings, session_id: str = None, user_id: str = Depends(get_current_user_id)):
    try:
        return service().configure(user_id, session_id, body)
    except (KeyError, ValueError, PermissionError, TaskExecutionConflict) as exc:
        translate(exc)


@router.post("/{session_id}/feedback", response_model=AmbientState)
async def ambient_feedback(session_id: str, body: AmbientFeedback, user_id: str = Depends(get_current_user_id)):
    try:
        return service().feedback(user_id, session_id, body)
    except (KeyError, ValueError, PermissionError, TaskExecutionConflict) as exc:
        translate(exc)


@router.post("/confirm", response_model=AmbientState)
@router.post("/{session_id}/confirm", response_model=AmbientState)
async def confirm_ambient(body: AmbientConfirmation, session_id: str = None, user_id: str = Depends(get_current_user_id)):
    try:
        return await service().confirm(user_id, session_id, body)
    except (KeyError, ValueError, PermissionError, TaskExecutionConflict) as exc:
        translate(exc)
