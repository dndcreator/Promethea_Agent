from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter

from ..dispatcher import get_gateway_server


router = APIRouter()


@router.get("/ops/capabilities")
async def ops_capabilities() -> Dict[str, Any]:
    gateway_server = get_gateway_server()

    config_service = getattr(gateway_server, "config_service", None)
    merged = config_service.get_merged_config(None) if config_service else {}
    sandbox_cfg = (merged.get("sandbox") or {}) if isinstance(merged, dict) else {}
    reasoning_cfg = (merged.get("reasoning") or {}) if isinstance(merged, dict) else {}
    memory_cfg = (merged.get("memory") or {}) if isinstance(merged, dict) else {}

    plugin_runtime = getattr(gateway_server, "plugin_runtime", None)
    plugin_count = len(getattr(plugin_runtime, "plugins", []) or []) if plugin_runtime else None

    return {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "capabilities": {
            "automation_triggers": ["/api/automation/webhook", "/api/automation/cron/wakeup"],
            "skills_catalog": "/api/skills/catalog",
            "skills_activate": "/api/skills/activate",
            "voice_turn": "/api/voice/turn",
            "model_failover": True,
            "sandbox_enabled": bool(sandbox_cfg.get("enabled", False)),
            "reasoning_enabled": bool(reasoning_cfg.get("enabled", False)),
            "memory_enabled": bool(memory_cfg.get("enabled", False)),
            "plugins_loaded": plugin_count,
            "reference_clients": ["web_ui", "cli", "http_api"],
            "product_shape": "local_assistant_plus_agent_runtime",
        },
    }


@router.get("/ops/abstractions")
async def ops_abstractions() -> Dict[str, Any]:
    """Machine-readable architecture contract for integrators."""

    return {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "identity": {
            "runtime_role": "agent_runtime_infrastructure",
            "default_product_form": "local_assistant",
            "statement": "Promethea is a local-first Agent Runtime. Built-in assistant surfaces are reference clients.",
        },
        "core_abstractions": [
            "conversation_runtime",
            "memory_lifecycle",
            "workflow_execution",
            "tool_and_skill_governance",
            "security_and_audit",
        ],
        "access_surfaces": {
            "http_api": "primary",
            "cli": "reference_client",
            "web_ui": "reference_client",
        },
        "ui_bound_features": [
            "memory_graph_visual_interaction",
            "avatar_and_theme_preferences",
            "modal_heavy_guided_operations",
        ],
        "principles": [
            "api_first_for_new_capabilities",
            "no_core_logic_exclusive_to_ui",
            "assistant_experience_must_remain_simple",
        ],
    }


@router.get("/ops/protocol")
async def ops_protocol() -> Dict[str, Any]:
    """Machine-readable gateway protocol contract for integrators."""

    return {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "protocol": {
            "name": "promethea_gateway_protocol",
            "version": "1.0",
            "api_contract": {
                "default_http_namespace": "/api",
                "current_api_version": "v1",
                "supported_api_versions": ["v1"],
                "compatibility_policy": "additive_only_within_v1",
                "config_contract_endpoint": "/api/config/contract",
            },
            "transports": {
                "http": {
                    "base_path": "/api",
                    "streaming": "sse_for_chat",
                },
                "websocket": {
                    "path": "/gateway/ws/{device_id}",
                    "message_types": ["req", "res", "event"],
                },
            },
            "request_envelope": {
                "required_fields": ["type", "id", "method", "params"],
                "optional_fields": ["idempotency_key", "timestamp"],
            },
            "response_envelope": {
                "required_fields": ["type", "id", "ok"],
                "optional_fields": ["payload", "error", "timestamp"],
            },
            "event_envelope": {
                "required_fields": ["type", "event", "payload"],
                "optional_fields": ["seq", "timestamp"],
            },
        },
        "semantics": {
            "idempotency": {
                "ws_request_message_key": True,
                "http_header_key": True,
                "accepted_http_headers": ["X-Idempotency-Key", "Idempotency-Key"],
                "note": "HTTP and WS both support idempotent execution for successful responses within cache TTL.",
            },
            "error_shape": {
                "normalized_http_error_object": {"code": "string", "message": "string"},
                "gateway_response_error_field": "string",
                "common_codes": [
                    "invalid_request",
                    "unauthorized",
                    "forbidden",
                    "not_found",
                    "service_unavailable",
                    "feature_disabled",
                    "timeout",
                    "gateway_error",
                ],
            },
            "long_run_pattern": {
                "run_identifier": "run_id",
                "lifecycle_events": ["*.started", "*.finished", "*.failed", "*.error", "*.completed"],
                "human_gate_supported": True,
            },
            "config_contract": {
                "inheritance_layers": ["default_template", "user_overrides", "env_runtime"],
                "env_only_secret_paths": [
                    "api.api_key",
                    "memory.api.api_key",
                    "memory.neo4j.password",
                ],
                "update_aliases": {
                    "config_data": "config",
                    "hot_reload": "options.hot_apply",
                    "hot_apply": "options.hot_apply",
                    "validate_config": "validate",
                },
            },
        },
    }


@router.get("/ops/runbook")
async def ops_runbook() -> Dict[str, Any]:
    return {
        "status": "success",
        "runbook": [
            "1) Check /api/status for service health.",
            "2) Check /api/ops/capabilities for feature toggles.",
            "3) Check /api/ops/abstractions for runtime/client boundaries.",
            "4) Check /api/ops/protocol for protocol contract details.",
            "5) Check /api/config/contract for config inheritance and update schema.",
            "6) If chat errors occur, validate /api/config runtime and API key.",
            "7) If memory errors occur, verify Neo4j and memory flags.",
            "8) For automation calls, verify AUTOMATION__TOKEN header.",
        ],
    }
