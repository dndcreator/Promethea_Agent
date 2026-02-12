from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gateway_integration import get_gateway_integration
from api_server import state
import config as config_module
from conversation_core import PrometheaConversation

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    user_id: str
    config: Dict[str, Any]


class ConfigResetRequest(BaseModel):
    user_id: str
    reset_to_default: bool = True


class ConfigSwitchModelRequest(BaseModel):
    user_id: str
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


@router.get("/config")
async def get_config(user_id: Optional[str] = None, raw: bool = False) -> Dict[str, Any]:
    config_service = _get_config_service()
    config_data = config_service.get_merged_config(user_id)
    if raw:
        return config_data
    return {"status": "success", "config": config_data}


@router.post("/config")
async def update_config_legacy(request: Dict[str, Any]) -> Dict[str, Any]:
    config_service = _get_config_service()
    config_payload = request.get("config", {}) or {}
    user_id = request.get("user_id")

    if user_id:
        result = await config_service.update_user_config(user_id, config_payload)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))
        return {
            "status": "success",
            "message": result.get("message", "Config updated"),
            "config": result.get("config", {}),
        }

    try:
        config_path, current_config = _load_default_config_dict()
        _deep_update(current_config, config_payload)

        with open(config_path, "w", encoding="utf-8") as file:
            json.dump(current_config, file, indent=4, ensure_ascii=False)

        reloaded = await config_service.reload_default_config()
        if not reloaded.get("success"):
            raise HTTPException(status_code=400, detail=reloaded.get("message", "Reload failed"))

        config_module.config = config_module.load_config()  # type: ignore[attr-defined]
        state.conversation = PrometheaConversation()  # type: ignore[misc]

        return {
            "status": "success",
            "message": "配置已更新并生效",
            "config": current_config,
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"更新配置失败: {error}")


@router.post("/config/update")
async def update_config(request: ConfigUpdateRequest) -> Dict[str, Any]:
    config_service = _get_config_service()
    result = await config_service.update_user_config(request.user_id, request.config)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))
    return result


@router.post("/config/reset")
async def reset_config(request: ConfigResetRequest) -> Dict[str, Any]:
    config_service = _get_config_service()
    result = await config_service.reset_user_config(request.user_id, request.reset_to_default)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Reset failed"))
    return result


@router.post("/config/switch-model")
async def switch_model(request: ConfigSwitchModelRequest) -> Dict[str, Any]:
    config_service = _get_config_service()
    result = await config_service.switch_model(
        request.user_id,
        request.model,
        request.api_key,
        request.base_url,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Switch model failed"))
    return result


@router.get("/config/diagnose")
async def diagnose_config(user_id: Optional[str] = None) -> Dict[str, Any]:
    config_service = _get_config_service()
    return config_service.diagnose_config(user_id)


@router.post("/config/reload")
async def reload_config() -> Dict[str, Any]:
    config_service = _get_config_service()
    result = await config_service.reload_default_config()

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Reload failed"))
    return result
