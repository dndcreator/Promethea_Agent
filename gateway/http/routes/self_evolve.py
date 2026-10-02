from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from gateway_integration import get_gateway_integration

from .auth import get_current_user_id


router = APIRouter(prefix="/self-evolve", tags=["self-evolve"])


class SelfEvolveCreateTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    capability_id: str = Field(min_length=2, max_length=48)
    version: str = Field(default="1.0.0", min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=500)
    commands: List[Dict[str, Any]] = Field(min_length=1)
    acceptance_criteria: Optional[List[str]] = None


class SelfEvolveContextRequest(BaseModel):
    max_chars_per_file: Optional[int] = Field(default=None, ge=200, le=20000)


class SelfEvolveSelfModelRequest(BaseModel):
    max_chars_per_file: Optional[int] = Field(default=None, ge=500, le=20000)


class SelfEvolveWriteFileRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(max_length=256000)


def _get_self_evolve_service():
    integration = get_gateway_integration()
    if not integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    gateway_server = integration.get_gateway_server()
    svc = getattr(gateway_server, "self_evolve_module", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Self-evolve module not initialized")
    cfg_service = getattr(gateway_server, "config_service", None)
    return svc, cfg_service


def _merged_user_config(config_service: Optional[Any], user_id: str) -> Dict[str, Any]:
    if config_service is None:
        return {}
    merged = config_service.get_merged_config(user_id)
    return merged if isinstance(merged, dict) else {}


def _ensure_enabled(svc: Any, merged: Dict[str, Any]) -> Dict[str, Any]:
    profile = svc.resolve_profile(merged)
    if not bool(profile.get("enabled")):
        raise HTTPException(status_code=400, detail="self_evolve is disabled for current user")
    return profile


def _http_error_from_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, TimeoutError):
        return HTTPException(status_code=408, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/status")
async def self_evolve_status(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    snapshot = svc.status_snapshot(merged, user_id=current_user_id)
    return {
        "status": "success",
        "user_id": current_user_id,
        "self_evolve": snapshot,
    }


@router.post("/tasks")
async def self_evolve_create_task(
    request: SelfEvolveCreateTaskRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.create_task(
            goal=request.goal,
            capability_id=request.capability_id,
            version=request.version,
            description=request.description,
            commands=list(request.commands),
            acceptance_criteria=list(request.acceptance_criteria or []),
            user_id=current_user_id,
        )
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.get("/tasks")
async def self_evolve_list_tasks(
    limit: int = 20,
    task_status: str = Query(default="", alias="status"),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    profile = _ensure_enabled(svc, merged)
    max_limit = int(profile.get("max_tasks_list") or 50)
    resolved_limit = max(1, min(int(limit), max_limit))
    try:
        out = await svc.list_tasks(limit=resolved_limit, status=str(task_status or ""), user_id=current_user_id)
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.get("/tasks/{task_id}")
async def self_evolve_get_task(
    task_id: str,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.get_task(task_id=task_id, user_id=current_user_id)
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.post("/tasks/{task_id}/context")
async def self_evolve_collect_context(
    task_id: str,
    request: SelfEvolveContextRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    profile = _ensure_enabled(svc, merged)
    max_chars = int(request.max_chars_per_file or profile.get("max_context_chars_per_file") or 4000)
    try:
        out = await svc.collect_context(
            task_id=task_id,
            max_chars_per_file=max_chars,
            user_id=current_user_id,
        )
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.get("/self-model")
async def self_evolve_get_self_model(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.get_self_model()
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.post("/self-model/refresh")
async def self_evolve_refresh_self_model(
    request: SelfEvolveSelfModelRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    profile = _ensure_enabled(svc, merged)
    max_chars = int(request.max_chars_per_file or profile.get("max_context_chars_per_file") or 5000)
    try:
        out = await svc.build_self_model(max_chars_per_file=max_chars)
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.put("/tasks/{task_id}/files")
async def self_evolve_write_file(
    task_id: str,
    request: SelfEvolveWriteFileRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.write_file(
            task_id=task_id,
            path=request.path,
            content=request.content,
            user_id=current_user_id,
        )
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.post("/tasks/{task_id}/validate")
async def self_evolve_validate(
    task_id: str,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.validate(task_id=task_id, user_id=current_user_id)
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.post("/tasks/{task_id}/publish")
async def self_evolve_publish(
    task_id: str,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.publish(task_id=task_id, user_id=current_user_id)
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc
