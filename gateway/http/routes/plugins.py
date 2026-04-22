from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.plugins.runtime import get_active_plugin_registry
from gateway_integration import get_gateway_integration

from .auth import get_current_user_id
from ..dispatcher import get_gateway_server


router = APIRouter()


class PluginValidateRequest(BaseModel):
    plugin_id: str
    config: Dict[str, Any] = Field(default_factory=dict)


class PluginApplyRequest(BaseModel):
    plugin_id: str
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    should_validate: bool = Field(default=True, alias="validate")


def _require_config_service():
    gateway_server = get_gateway_server()
    config_service = getattr(gateway_server, "config_service", None)
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return config_service


def _schema_type_ok(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def _validate_value_against_schema(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    expected_type = str(schema.get("type") or "").strip().lower()
    if expected_type and not _schema_type_ok(expected_type, value):
        errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
        return

    enum_vals = schema.get("enum")
    if isinstance(enum_vals, list) and enum_vals and value not in enum_vals:
        errors.append(f"{path}: must be one of {enum_vals}")

    if isinstance(value, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, field_schema in properties.items():
            if key in value and isinstance(field_schema, dict):
                _validate_value_against_schema(value[key], field_schema, f"{path}.{key}", errors)


def _validate_plugin_config(plugin_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    registry = get_active_plugin_registry()
    if not registry:
        return {"ok": False, "errors": ["plugin registry not initialized"], "plugin_id": plugin_id}

    record = next((p for p in registry.plugins if p.id == plugin_id), None)
    if record is None:
        return {"ok": False, "errors": [f"plugin not found: {plugin_id}"], "plugin_id": plugin_id}

    schema = dict(record.config_schema or {})
    errors: List[str] = []
    _validate_value_against_schema(config, schema, "config", errors)
    return {
        "ok": len(errors) == 0,
        "plugin_id": plugin_id,
        "errors": errors,
        "schema_type": str(schema.get("type") or ""),
    }


@router.get("/plugins/catalog")
async def get_plugins_catalog(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    config_service = _require_config_service()
    integration = get_gateway_integration()
    if integration and hasattr(integration, "maybe_refresh_plugins"):
        try:
            await integration.maybe_refresh_plugins()
        except Exception:
            pass

    registry = get_active_plugin_registry()
    merged = config_service.get_merged_config(user_id)
    merged_plugins = merged.get("plugins") if isinstance(merged, dict) and isinstance(merged.get("plugins"), dict) else {}

    rows: List[Dict[str, Any]] = []
    for plugin in (registry.plugins if registry else []):
        merged_entry = merged_plugins.get(plugin.id) if isinstance(merged_plugins, dict) else {}
        merged_cfg = merged_entry if isinstance(merged_entry, dict) else {}
        enabled = bool(merged_cfg.get("enabled", plugin.enabled))
        config_row = merged_cfg.get("config") if isinstance(merged_cfg.get("config"), dict) else {}
        rows.append(
            {
                "id": plugin.id,
                "name": plugin.name or plugin.id,
                "kind": str(plugin.kind.value) if plugin.kind else "",
                "description": plugin.description or "",
                "version": plugin.version or "",
                "status": plugin.status,
                "enabled": enabled,
                "config": config_row,
                "configSchema": dict(plugin.config_schema or {}),
                "uiSchema": dict(plugin.ui_schema or {}),
                "capabilities": dict(plugin.capabilities or {}),
            }
        )

    diagnostics = [d.model_dump() for d in (registry.diagnostics if registry else [])]
    return {
        "status": "success",
        "user_id": user_id,
        "total": len(rows),
        "plugins": rows,
        "diagnostics": diagnostics,
    }


@router.post("/plugins/validate")
async def validate_plugin_config(
    request: PluginValidateRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    _ = user_id
    plugin_id = str(request.plugin_id or "").strip()
    if not plugin_id:
        raise HTTPException(status_code=400, detail="plugin_id is required")
    return _validate_plugin_config(plugin_id, dict(request.config or {}))


@router.post("/plugins/apply")
async def apply_plugin_config(
    request: PluginApplyRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _require_config_service()
    plugin_id = str(request.plugin_id or "").strip()
    if not plugin_id:
        raise HTTPException(status_code=400, detail="plugin_id is required")

    config_payload = dict(request.config or {})
    if request.should_validate:
        validation = _validate_plugin_config(plugin_id, config_payload)
        if not validation.get("ok"):
            raise HTTPException(status_code=400, detail={"message": "plugin config validation failed", "errors": validation.get("errors", [])})

    result = await config_service.update_user_config(
        user_id,
        {"plugins": {plugin_id: {"enabled": bool(request.enabled), "config": config_payload}}},
        validate=False,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "failed to update plugin config"))

    integration = get_gateway_integration()
    if integration and hasattr(integration, "maybe_refresh_plugins"):
        try:
            await integration.maybe_refresh_plugins(force=True)
        except Exception:
            pass

    return {
        "status": "success",
        "user_id": user_id,
        "plugin_id": plugin_id,
        "enabled": bool(request.enabled),
        "config": config_payload,
    }
