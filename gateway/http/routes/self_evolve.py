from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from gateway_integration import get_gateway_integration

from .auth import get_current_user_id


router = APIRouter(prefix="/self-evolve", tags=["self-evolve"])


class SelfEvolveCreateTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    target_files: List[str] = Field(min_length=1)
    acceptance_criteria: Optional[List[str]] = None


class SelfEvolveContextRequest(BaseModel):
    max_chars_per_file: Optional[int] = Field(default=None, ge=200, le=20000)


class SelfEvolveSelfModelRequest(BaseModel):
    max_chars_per_file: Optional[int] = Field(default=None, ge=500, le=20000)


class SelfEvolvePatchRequest(BaseModel):
    path: str = Field(min_length=1)
    old: str = Field(min_length=1)
    new: str = ""
    count: int = Field(default=1, ge=1, le=1000)
    create_backup: bool = True


class SelfEvolveValidateRequest(BaseModel):
    command: str = Field(min_length=1)
    cwd: str = "."
    timeout: Optional[int] = Field(default=None, ge=5, le=1800)


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
    snapshot = svc.status_snapshot(merged)
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
            target_files=list(request.target_files),
            acceptance_criteria=list(request.acceptance_criteria or []),
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
        out = await svc.list_tasks(limit=resolved_limit, status=str(task_status or ""))
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
        out = await svc.get_task(task_id=task_id)
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
        out = await svc.collect_context(task_id=task_id, max_chars_per_file=max_chars)
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


@router.post("/tasks/{task_id}/patch")
async def self_evolve_apply_patch(
    task_id: str,
    request: SelfEvolvePatchRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    _ensure_enabled(svc, merged)
    try:
        out = await svc.apply_patch(
            task_id=task_id,
            path=request.path,
            old=request.old,
            new=request.new,
            count=int(request.count),
            create_backup=bool(request.create_backup),
        )
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc


@router.post("/tasks/{task_id}/validate")
async def self_evolve_validate(
    task_id: str,
    request: SelfEvolveValidateRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_self_evolve_service()
    merged = _merged_user_config(config_service, current_user_id)
    profile = _ensure_enabled(svc, merged)
    timeout = int(request.timeout or profile.get("max_validate_timeout_seconds") or 180)
    try:
        out = await svc.validate(
            task_id=task_id,
            command=request.command,
            cwd=request.cwd,
            timeout=timeout,
        )
        return {"status": "success", "user_id": current_user_id, **out}
    except Exception as exc:
        raise _http_error_from_exception(exc) from exc
