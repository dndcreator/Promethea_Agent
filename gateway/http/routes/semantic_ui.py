"""Owner-scoped expressions and feedback, never arbitrary host execution."""
from fastapi import APIRouter, Depends, HTTPException

from gateway.public_contracts import SemanticUIFeedback, SemanticExpression, SemanticSurface, SemanticUIState
from gateway.task_service import TaskExecutionConflict
from ..dispatcher import get_gateway_server
from .auth import get_current_user_id

router = APIRouter(prefix="/semantic-ui", tags=["semantic-ui"])


def component():
    model = getattr(get_gateway_server(), "self_model_service", None)
    if model is None:
        raise HTTPException(503, "SelfModel is not initialized")
    return model.semantic_ui


def translate(exc):
    status = 409 if isinstance(exc, TaskExecutionConflict) else 404 if isinstance(exc, KeyError) else 403 if isinstance(exc, PermissionError) else 503 if isinstance(exc, (TimeoutError, OSError)) else 422
    raise HTTPException(status, detail=str(exc)) from exc


@router.get("", response_model=SemanticUIState)
async def get_expressions(user_id: str = Depends(get_current_user_id)):
    return component().view(user_id)


@router.post("/context")
async def observe_surface(body: SemanticSurface, user_id: str = Depends(get_current_user_id)):
    try:
        return await component().observe_surface(user_id, body)
    except (KeyError, ValueError, TaskExecutionConflict, PermissionError, TimeoutError, OSError) as exc:
        translate(exc)


@router.post("/{expression_id}/feedback", response_model=SemanticExpression)
async def expression_feedback(expression_id: str, body: SemanticUIFeedback, user_id: str = Depends(get_current_user_id)):
    try:
        return await component().feedback(user_id, expression_id, body)
    except (KeyError, ValueError, TaskExecutionConflict, PermissionError, TimeoutError, OSError) as exc:
        translate(exc)
