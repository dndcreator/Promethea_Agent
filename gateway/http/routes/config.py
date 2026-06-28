from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config as config_module
from gateway.config_protocol import normalize_config_update_params
from gateway.soul_service import build_soul_response_payload
from gateway.user_secrets import get_user_secrets_status, update_user_secrets
from gateway_integration import get_gateway_integration

from .auth import get_current_user_id

router = APIRouter()

ENV_ONLY_SECRET_PATHS = [
    "api.api_key",
    "api.base_url",
    "api.model",
    "api.failover_models",
    "memory.api.api_key",
    "memory.api.base_url",
    "memory.api.model",
    "memory.api.use_main_api",
    "memory.neo4j.enabled",
    "memory.neo4j.uri",
    "memory.neo4j.username",
    "memory.neo4j.password",
    "memory.neo4j.database",
    "memory.store_backend",
    "memory.sqlite_graph_path",
    "memory.flat_memory_path",
    "search.provider",
    "search.brave_api_key",
    "search.tavily_api_key",
    "search.serpapi_api_key",
    "search.searxng_url",
]

SIMPLE_CONFIG_FIELDS = [
    "agent_name",
    "system_prompt",
    "memory.enabled",
    "memory.profile",
    "reasoning.enabled",
    "system.stream_mode",
    "org_brain.enabled",
]

ADVANCED_CONFIG_FIELDS = [
    "api.temperature",
    "api.max_tokens",
    "api.max_history_rounds",
    "memory.migration.mode",
    "memory.migration.source_backend",
    "memory.migration.target_backend",
    "memory.migration.checkpoint",
    "memory.warm_layer.enabled",
    "memory.warm_layer.clustering_threshold",
    "memory.warm_layer.min_cluster_size",
    "memory.cold_layer.max_summary_length",
    "memory.cold_layer.compression_threshold",
    "system.debug",
    "system.log_level",
    "org_brain.org_id",
    "org_brain.recall_priority",
    "org_brain.confirmation_queue",
    "org_brain.audience_default",
    "org_brain.max_upload_bytes",
    "org_brain.allowed_suffixes",
    "org_brain.recall_top_k_default",
    "org_brain.recall_context_type_default",
    "org_brain.chat_top_k",
    "org_brain.chat_context_type",
    "org_brain.summary_label",
    "org_brain.summary_max_items",
    "org_brain.extract_text_max_chars",
    "org_brain.heuristic_max_lines",
    "org_brain.heuristic_max_items",
]


class ConfigUpdateOptions(BaseModel):
    hot_apply: bool = False


class ConfigUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    config_data: Optional[Dict[str, Any]] = None
    options: Optional[ConfigUpdateOptions] = None
    hot_apply: Optional[bool] = None
    hot_reload: Optional[bool] = None
    validate_config: Optional[bool] = None
    validate_flag: Optional[bool] = Field(default=None, alias="validate")


class ConfigResetRequest(BaseModel):
    user_id: Optional[str] = None
    reset_to_default: bool = True


class ConfigSwitchModelRequest(BaseModel):
    user_id: Optional[str] = None
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class SecretsUpdateRequest(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)


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


def _sanitize_config_for_client(config_data: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(config_data or {})
    if isinstance(sanitized.get("api"), dict):
        for key in ("api_key", "base_url", "model", "failover_models"):
            sanitized["api"].pop(key, None)
    if isinstance(sanitized.get("memory"), dict):
        mem = sanitized["memory"]
        if isinstance(mem.get("api"), dict):
            for key in ("api_key", "base_url", "model", "use_main_api"):
                mem["api"].pop(key, None)
        if isinstance(mem.get("neo4j"), dict):
            for key in ("enabled", "uri", "username", "password", "database"):
                mem["neo4j"].pop(key, None)
        for key in ("store_backend", "sqlite_graph_path", "flat_memory_path"):
            mem.pop(key, None)
    if isinstance(sanitized.get("search"), dict):
        for key in ("provider", "brave_api_key", "tavily_api_key", "serpapi_api_key", "searxng_url"):
            sanitized["search"].pop(key, None)
    return sanitized


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
        return default
    return bool(value)


def _build_basic_config_view(config_data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = config_data or {}
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    reasoning = cfg.get("reasoning") if isinstance(cfg.get("reasoning"), dict) else {}
    system = cfg.get("system") if isinstance(cfg.get("system"), dict) else {}
    org_brain = cfg.get("org_brain") if isinstance(cfg.get("org_brain"), dict) else {}
    return {
        "config_version": cfg.get("config_version"),
        "agent_name": cfg.get("agent_name"),
        "system_prompt": cfg.get("system_prompt"),
        "memory": {
            "enabled": _to_bool(memory.get("enabled"), default=True),
            "profile": memory.get("profile", "balanced"),
            "store_backend": memory.get("store_backend", "neo4j"),
        },
        "reasoning": {
            "enabled": _to_bool(reasoning.get("enabled"), default=True),
            "mode": reasoning.get("mode", "react_tot"),
        },
        "system": {
            "stream_mode": _to_bool(system.get("stream_mode"), default=True),
        },
        "org_brain": {
            "enabled": _to_bool(org_brain.get("enabled"), default=False),
            "org_id": org_brain.get("org_id", ""),
            "recall_priority": org_brain.get("recall_priority", "blend"),
            "confirmation_queue": _to_bool(org_brain.get("confirmation_queue"), default=True),
            "audience_default": org_brain.get("audience_default", "业务部门"),
        },
        "soul": build_soul_response_payload(cfg),
    }


def _load_default_config_dict() -> tuple[Path, Dict[str, Any]]:
    config_path = Path("config/default.json")
    if not config_path.exists():
        config_path = Path("config.json")

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8-sig") as file:
            return config_path, json.load(file)

    return config_path, config_module.PrometheaConfig().model_dump()


def _resolve_user_id(requested: Optional[str], current_user_id: str) -> str:
    if requested and requested != current_user_id:
        raise HTTPException(status_code=403, detail="cross-user config access is forbidden")
    return current_user_id


def _normalize_config_update_request(request: ConfigUpdateRequest) -> Dict[str, Any]:
    raw = request.model_dump()
    if raw.get("validate") is None and request.validate_flag is not None:
        raw["validate"] = request.validate_flag
    return normalize_config_update_params(raw)


def _build_config_contract() -> Dict[str, Any]:
    return {
        "status": "success",
        "contract": {
            "name": "promethea_config_contract",
            "version": "1.1",
            "inheritance": {
                "layers": ["default_template", "user_overrides", "env_runtime"],
                "effective_order": "default_template(+env baseline) -> user_overrides; env-only secrets stay env-owned",
                "new_user_bootstrap": "default template is materialized as effective baseline, then user overrides are applied",
            },
            "env_only_secret_paths": ENV_ONLY_SECRET_PATHS,
            "update_api": {
                "path": "/api/config/update",
                "method": "POST",
                "canonical_shape": {
                    "user_id": "optional<string>",
                    "config": "object",
                    "options": {"hot_apply": "bool"},
                },
                "compat_aliases_accepted": {
                    "config_data": "alias_of_config",
                    "updates": "alias_of_config",
                    "hot_reload": "alias_of_options.hot_apply",
                    "hot_apply": "alias_of_options.hot_apply",
                    "validate_config": "alias_of_validate",
                    "validate": "legacy_validate_flag",
                },
            },
            "template_api": {
                "path": "/api/config/default-template",
                "method": "GET",
                "query": {
                    "view": "basic|full",
                    "raw": "bool",
                },
            },
            "effective_api": {
                "path": "/api/config/effective",
                "method": "GET",
                "query": {
                    "view": "basic|full",
                    "include_layers": "bool",
                    "raw": "bool",
                },
                "source_values": [
                    "default_template",
                    "user_override",
                    "env_only_secret",
                    "unknown",
                ],
            },
            "ui_schema_api": {
                "path": "/api/config/ui-schema",
                "method": "GET",
                "query": {"view": "simple|advanced|both"},
            },
            "soul_api": {
                "path": "/api/config/soul",
                "method": "GET",
            },
            "ui_profiles": {
                "simple_fields": SIMPLE_CONFIG_FIELDS,
                "advanced_fields": ADVANCED_CONFIG_FIELDS,
            },
        },
    }


@router.get("/config")
async def get_config(
    user_id: Optional[str] = None,
    raw: bool = False,
    view: Literal["basic", "full"] = "full",
    include_sources: bool = False,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    source_paths = SIMPLE_CONFIG_FIELDS if (include_sources and view == "basic") else None
    effective_bundle = config_service.get_effective_config_with_sources(
        resolved_user_id,
        field_paths=source_paths,
    )
    full_config = _sanitize_config_for_client(effective_bundle.get("effective") or {})
    config_data = _build_basic_config_view(full_config) if view == "basic" else full_config
    warnings = config_service.get_deprecation_warnings(resolved_user_id)
    if raw:
        return config_data
    payload = {
        "status": "success",
        "user_id": resolved_user_id,
        "config": config_data,
        "soul": build_soul_response_payload(full_config),
        "view": view,
        "warnings": warnings,
    }
    if include_sources:
        payload["sources"] = effective_bundle.get("sources") or {}
    return payload


@router.get("/config/secrets")
async def get_config_secrets(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    status = get_user_secrets_status(current_user_id)
    return {
        "status": "success",
        "user_id": current_user_id,
        "secrets": status,
        "message": "Sensitive runtime settings are stored in the user secrets.env file and are not returned in full.",
    }


@router.post("/config/secrets")
async def update_config_secrets(
    request: SecretsUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    status = update_user_secrets(current_user_id, request.values)
    return {
        "status": "success",
        "user_id": current_user_id,
        "secrets": status,
        "message": "Sensitive runtime settings saved to user secrets.env.",
    }


@router.get("/config/contract")
async def get_config_contract(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    payload = _build_config_contract()
    payload["user_id"] = current_user_id
    return payload


@router.get("/config/default-template")
async def get_default_template(
    raw: bool = False,
    view: Literal["basic", "full"] = "full",
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_path, template = _load_default_config_dict()
    sanitized_template = _sanitize_config_for_client(template)
    template_view = _build_basic_config_view(sanitized_template) if view == "basic" else sanitized_template
    if raw:
        return template_view

    return {
        "status": "success",
        "user_id": current_user_id,
        "template": template_view,
        "view": view,
        "source": str(config_path),
        "env_only_secret_paths": ENV_ONLY_SECRET_PATHS,
        "ui_profiles": {
            "simple_fields": SIMPLE_CONFIG_FIELDS,
            "advanced_fields": ADVANCED_CONFIG_FIELDS,
        },
    }


@router.get("/config/effective")
async def get_effective_config(
    user_id: Optional[str] = None,
    raw: bool = False,
    view: Literal["basic", "full"] = "full",
    include_layers: bool = False,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    source_paths = SIMPLE_CONFIG_FIELDS if view == "basic" else None
    effective_bundle = config_service.get_effective_config_with_sources(
        resolved_user_id,
        field_paths=source_paths,
    )
    full_config = _sanitize_config_for_client(effective_bundle.get("effective") or {})
    config_data = _build_basic_config_view(full_config) if view == "basic" else full_config
    if raw:
        return config_data

    payload: Dict[str, Any] = {
        "status": "success",
        "user_id": resolved_user_id,
        "view": view,
        "effective": config_data,
        "soul": build_soul_response_payload(full_config),
        "sources": effective_bundle.get("sources") or {},
    }
    if include_layers:
        payload["layers"] = {
            "default_template": _sanitize_config_for_client(
                (effective_bundle.get("layers") or {}).get("default_template") or {}
            ),
            "user_overrides": _sanitize_config_for_client(
                (effective_bundle.get("layers") or {}).get("user_overrides") or {}
            ),
        }
    return payload


@router.get("/config/ui-schema")
async def get_config_ui_schema(
    view: Literal["simple", "advanced", "both"] = "both",
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    _ = current_user_id
    profile_payload: Dict[str, Any] = {}
    if view in {"simple", "both"}:
        profile_payload["simple"] = {"fields": SIMPLE_CONFIG_FIELDS}
    if view in {"advanced", "both"}:
        profile_payload["advanced"] = {"fields": ADVANCED_CONFIG_FIELDS}
    return {"status": "success", "view": view, "profiles": profile_payload}


@router.post("/config")
async def update_config_legacy(
    request: Dict[str, Any],
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    config_payload: Dict[str, Any] = {}
    if isinstance(request.get("config_data"), dict):
        _deep_update(config_payload, request.get("config_data") or {})
    if isinstance(request.get("config"), dict):
        _deep_update(config_payload, request.get("config") or {})
    requested_user_id = request.get("user_id")
    resolved_user_id = _resolve_user_id(requested_user_id, current_user_id)

    result = await config_service.update_user_config(resolved_user_id, config_payload)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))

    return {
        "status": "success",
        "user_id": resolved_user_id,
        "message": result.get("message", "Config updated"),
        "config": _sanitize_config_for_client(result.get("config", {})),
    }


@router.post("/config/update")
async def update_config(
    request: ConfigUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(request.user_id, current_user_id)
    normalized = _normalize_config_update_request(request)
    result = await config_service.update_user_config(
        resolved_user_id,
        normalized["config"],
        validate=bool(normalized["validate"]),
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))

    hot_apply_requested = bool(normalized["hot_apply"])
    hot_apply_payload: Dict[str, Any] = {"requested": hot_apply_requested, "success": False}
    if hot_apply_requested:
        try:
            integration = _get_gateway_integration_or_503()
            reload_result = await integration.reload_config()
            hot_apply_payload["success"] = _to_bool(reload_result.get("success"), default=False)
            hot_apply_payload["message"] = reload_result.get("message") or (
                "runtime reloaded" if hot_apply_payload["success"] else None
            )
            if hot_apply_payload["success"]:
                hot_apply_payload["reloaded_at"] = reload_result.get("reloaded_at")
        except HTTPException as exc:
            hot_apply_payload["message"] = str(exc.detail)
        except Exception as exc:  # pragma: no cover - defensive path
            hot_apply_payload["message"] = str(exc)

    return {
        **result,
        "user_id": resolved_user_id,
        "config": _sanitize_config_for_client(result.get("config", {})),
        "hot_apply": hot_apply_payload,
    }


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
    return {**result, "user_id": resolved_user_id, "config": _sanitize_config_for_client(result.get("config", {}))}


@router.get("/config/diagnose")
async def diagnose_config(
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    payload = config_service.diagnose_config(resolved_user_id)
    payload["config"] = _sanitize_config_for_client(payload.get("config") or {})
    return payload


@router.post("/config/reload")
async def reload_config(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    # Keep endpoint for compatibility, but delegate all reload behavior to ConfigService.
    config_service = _get_config_service()
    result = await config_service.reload_default_config()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Reload failed"))

    config_module.config = config_module.load_config()  # type: ignore[attr-defined]
    return {"status": "success", "user_id": current_user_id, **result}


@router.get("/config/runtime/scoped")
async def get_runtime_config_scoped(
    scope: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    runtime = config_service.get_runtime_config(resolved_user_id, scope=scope)
    runtime = _sanitize_config_for_client(runtime)
    return {"status": "success", "user_id": resolved_user_id, "runtime": runtime, "scope": scope}


@router.get("/config/preferences")
async def get_user_preferences(
    scope: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    prefs = config_service.get_user_preferences(resolved_user_id, scope=scope)
    prefs = _sanitize_config_for_client(prefs)
    return {"status": "success", "user_id": resolved_user_id, "preferences": prefs, "scope": scope}


@router.get("/config/soul")
async def get_soul_config(
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    cfg = config_service.get_merged_config(resolved_user_id)
    return {
        "status": "success",
        "user_id": resolved_user_id,
        "soul": build_soul_response_payload(cfg),
    }


@router.get("/config/tool-policy")
async def get_tool_policy_config(
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    payload = config_service.get_tool_policy_config(resolved_user_id, agent_id=agent_id)
    return {"status": "success", "user_id": resolved_user_id, "tool_policy": payload}


@router.get("/config/channel/{channel_id}")
async def get_channel_config(
    channel_id: str,
    user_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    config_service = _get_config_service()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)
    payload = config_service.get_channel_config(channel_id, user_id=resolved_user_id)
    payload = _sanitize_config_for_client(payload)
    return {"status": "success", "user_id": resolved_user_id, "channel_id": channel_id, "config": payload}


@router.get("/config/runtime")
async def get_runtime_config(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    config_service = _get_config_service()
    runtime = config_service.get_runtime_config(current_user_id)
    runtime = _sanitize_config_for_client(runtime)
    return {
        "status": "success",
        "user_id": current_user_id,
        "runtime": runtime,
        "precedence": "defaults(+env baseline) > user overrides; env-only secrets remain env-owned",
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




