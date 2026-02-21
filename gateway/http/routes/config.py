from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config as config_module
from gateway_integration import get_gateway_integration

from .auth import get_current_user_id

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    config: Dict[str, Any]


class ConfigResetRequest(BaseModel):
    user_id: Optional[str] = None
    reset_to_default: bool = True


class ConfigSwitchModelRequest(BaseModel):
    user_id: Optional[str] = None
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


def _get_config_service():
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return gateway_server.config_service


def _get_gateway_integration_or_503():
    integration = get_gateway_integration()
    if not integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    return integration


def _deep_update(base_dict: Dict[str, Any], update_dict: Dict[str, Any]) -> None:
    for key, value in update_dict.items():
        if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
            _deep_update(base_dict[key], value)
        else:
            base_dict[key] = value


def _load_default_config_dict() -> tuple[Path, Dict[str, Any]]:
    config_path = Path("config/default.json")
    if not config_path.exists():
        config_path = Path("config.json")

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as file:
            return config_path, json.load(file)

    return config_path, config_module.PrometheaConfig().model_dump()


def _resolve_user_id(requested: Optional[str], current_user_id: str) -> str:
    if requested and requested != current_user_id:
        raise HTTPException(status_code=403, detail="cross-user config access is forbidden")
    return current_user_id


@router.get("/config")
async def get_config(
    user_id: Optional[str] = None,
    raw: bool = False,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    config_data = config_service.get_merged_config(resolved_user_id)
    if raw:
        return config_data
    return {"status": "success", "user_id": resolved_user_id, "config": config_data}


@router.post("/config")
async def update_config_legacy(
    request: Dict[str, Any],
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    config_payload = request.get("config", {}) or {}
    requested_user_id = request.get("user_id")
    resolved_user_id = _resolve_user_id(requested_user_id, current_user_id)

    result = await config_service.update_user_config(resolved_user_id, config_payload)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))

    return {
        "status": "success",
        "user_id": resolved_user_id,
        "message": result.get("message", "Config updated"),
        "config": result.get("config", {}),
    }


@router.post("/config/update")
async def update_config(
    request: ConfigUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(request.user_id, current_user_id)
    result = await config_service.update_user_config(resolved_user_id, request.config)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))
    return {**result, "user_id": resolved_user_id}


@router.post("/config/reset")
async def reset_config(
    request: ConfigResetRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(request.user_id, current_user_id)
    result = await config_service.reset_user_config(resolved_user_id, request.reset_to_default)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Reset failed"))
    return {**result, "user_id": resolved_user_id}


@router.post("/config/switch-model")
async def switch_model(
    request: ConfigSwitchModelRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(request.user_id, current_user_id)
    result = await config_service.switch_model(
        resolved_user_id,
        request.model,
        request.api_key,
        request.base_url,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Switch model failed"))
    return {**result, "user_id": resolved_user_id}


@router.get("/config/diagnose")
async def diagnose_config(
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    return config_service.diagnose_config(resolved_user_id)


@router.post("/config/reload")
async def reload_config(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    # Keep endpoint for compatibility, but delegate all reload behavior to ConfigService.
    config_service = _get_config_service()
    result = await config_service.reload_default_config()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Reload failed"))

    config_module.config = config_module.load_config()  # type: ignore[attr-defined]
    return {"status": "success", "user_id": current_user_id, **result}


@router.get("/config/runtime")
async def get_runtime_config(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    integration = _get_gateway_integration_or_503()
    return {
        "status": "success",
        "user_id": current_user_id,
        "runtime": integration.config,
        "precedence": "env > gateway_config.json > defaults",
    }


@router.post("/config/runtime/reload")
async def reload_runtime_config(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    integration = _get_gateway_integration_or_503()
    result = await integration.reload_config()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "runtime reload failed"))
    return {"status": "success", "user_id": current_user_id, **result}


@router.post("/config/default")
async def update_default_config(_: Dict[str, Any], __: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    raise HTTPException(status_code=403, detail="default config mutation is disabled via API")

