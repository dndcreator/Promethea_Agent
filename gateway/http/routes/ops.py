from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Request

from ..dispatcher import get_gateway_server
from .. import state
from ..surface_discovery import build_surface_payload, collect_http_surface_from_routes
from gateway.protocol_contracts import build_domain_contracts, build_ws_method_contracts
from ..http_contracts import build_http_contracts
from gateway.protocol import RequestType


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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "capabilities": {
            "automation_triggers": ["/api/automation/webhook", "/api/automation/cron/wakeup"],
            "skills_catalog": "/api/skills/catalog",
            "skills_activate": "/api/skills/activate",
            "voice_turn": "/api/voice/turn",
            "model_failover": True,
            "sandbox_enabled": bool(sandbox_cfg.get("enabled", False)),
            "reasoning_enabled": bool(reasoning_cfg.get("enabled", True)),
            "memory_enabled": bool(memory_cfg.get("enabled", True)),
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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "protocol": {
            "name": "promethea_gateway_protocol",
            "version": "1.0",
            "revision": "2026-03-23",
            "api_contract": {
                "default_http_namespace": "/api",
                "current_api_version": "v1",
                "supported_api_versions": ["v1"],
                "compatibility_policy": "additive_only_within_v1",
                "config_contract_endpoint": "/api/config/contract",
                "config_template_endpoint": "/api/config/default-template",
                "http_contracts_endpoint": "/api/ops/http-contracts",
                "surface_discovery_endpoint": "/api/ops/surfaces",
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
                "normalized_http_error_object": {
                    "code": "string",
                    "message": "string",
                    "retryable": "bool",
                    "dependency": "string",
                    "advice": "string",
                    "trace_id": "string",
                },
                "gateway_response_error_field": "string",
                "gateway_response_payload_error_detail": {
                    "code": "string",
                    "message": "string",
                    "retryable": "bool",
                    "dependency": "string",
                    "advice": "string",
                    "trace_id": "string",
                },
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
            "surface_discovery": {
                "authoritative_endpoint": "/api/ops/surfaces",
                "note": "Integrators should prefer runtime-discovered surfaces over hardcoded route lists.",
            },
            "config_contract": {
                "inheritance_layers": ["default_template", "user_overrides", "env_runtime"],
                "default_template_source_api": "/api/config/default-template",
                "canonical_update_shape": {
                    "config": "object",
                    "options": {"hot_apply": "bool"},
                    "validate": "bool",
                },
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
            "domains": build_domain_contracts(),
            "governance": {
                "stability_levels": ["stable", "compat", "legacy"],
                "deprecation_policy": "legacy endpoints remain available with canonical endpoint hints before removal",
                "change_policy": "breaking changes require version bump and migration notes",
            },
        },
    }


@router.get("/ops/readiness")
async def ops_readiness() -> Dict[str, Any]:
    gateway_server = get_gateway_server()
    services = gateway_server.get_services_health()
    failed = sorted([name for name, ok in services.items() if not bool(ok)])
    total = max(1, len(services))
    ok_count = total - len(failed)
    ratio = ok_count / total
    startup = dict(state.startup_report or {})
    startup_status = str(startup.get("status") or "unknown")

    level = "healthy" if ratio >= 0.99 else ("degraded" if ratio >= 0.6 else "unhealthy")
    if startup_status == "failed":
        level = "unhealthy"
    elif startup_status == "degraded" and level == "healthy":
        level = "degraded"

    critical = {"conversation_service", "config_service", "tool_service"}
    critical_failed = sorted([name for name in failed if name in critical])
    go_no_go = "go"
    reason = "all critical services ready"
    if critical_failed:
        go_no_go = "no-go"
        reason = f"critical services unavailable: {', '.join(critical_failed)}"

    recommendations = []
    for name in failed:
        recommendations.append({"component": name, "action": f"initialize {name} and verify dependencies"})
    if startup_status in {"degraded", "failed"}:
        recommendations.append(
            {
                "component": "startup",
                "action": "review startup_report components and fix failed/degraded boot steps",
            }
        )

    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "readiness": {
            "level": level,
            "go_no_go": go_no_go,
            "reason": reason,
            "service_summary": {"total": total, "ok": ok_count, "failed": len(failed), "ratio": ratio},
            "failed_services": failed,
            "critical_failed_services": critical_failed,
            "startup_status": startup_status,
            "recommendations": recommendations,
        },
    }


@router.get("/ops/http-contracts")
async def ops_http_contracts(request: Request) -> Dict[str, Any]:
    contracts = build_http_contracts(routes=request.app.routes)
    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contracts": contracts,
        "count": len(contracts),
    }


@router.get("/ops/methods")
async def ops_methods() -> Dict[str, Any]:
    methods = build_ws_method_contracts()
    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "methods": methods,
        "count": len(methods),
    }


@router.get("/ops/framework-check")
async def ops_framework_check(request: Request) -> Dict[str, Any]:
    gateway_server = get_gateway_server()
    handler_methods = sorted(rt.value for rt in getattr(gateway_server, "_handlers", {}).keys())
    enum_methods = sorted(rt.value for rt in RequestType)
    method_contracts = build_ws_method_contracts()
    contract_methods = sorted(item["method"] for item in method_contracts)
    http_surface = collect_http_surface_from_routes(request.app.routes)
    http_contracts = build_http_contracts(routes=request.app.routes)
    http_surface_paths = {item["path"] for item in http_surface}
    contract_paths = {item["path"] for item in http_contracts}

    missing_handlers = sorted(set(enum_methods) - set(handler_methods))
    handler_orphans = sorted(set(handler_methods) - set(enum_methods))
    uncovered_contract_methods = sorted(set(enum_methods) - set(contract_methods))
    contract_orphan_methods = sorted(set(contract_methods) - set(enum_methods))
    uncovered_http_contract_paths = sorted(contract_paths - http_surface_paths)
    uncovered_http_surface_paths = sorted(http_surface_paths - contract_paths)

    ok = not any(
        [
            missing_handlers,
            handler_orphans,
            uncovered_contract_methods,
            contract_orphan_methods,
            uncovered_http_contract_paths,
            uncovered_http_surface_paths,
        ]
    )
    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ok": ok,
        "checks": {
            "ws": {
                "enum_methods": len(enum_methods),
                "handlers_registered": len(handler_methods),
                "contract_methods": len(contract_methods),
                "missing_handlers": missing_handlers,
                "handler_orphans": handler_orphans,
                "uncovered_contract_methods": uncovered_contract_methods,
                "contract_orphan_methods": contract_orphan_methods,
            },
            "http": {
                "surface_routes": len(http_surface),
                "contract_routes": len(http_contracts),
                "uncovered_contract_paths": uncovered_http_contract_paths,
                "uncovered_surface_paths": uncovered_http_surface_paths,
            },
        },
    }


@router.get("/ops/surfaces")
async def ops_surfaces(request: Request) -> Dict[str, Any]:
    return build_surface_payload(request.app.routes)


@router.get("/ops/runbook")
async def ops_runbook() -> Dict[str, Any]:
    return {
        "status": "success",
        "runbook": [
            "1) Check /api/status for service health.",
            "2) Check /api/ops/capabilities for feature toggles.",
            "3) Check /api/ops/abstractions for runtime/client boundaries.",
            "4) Check /api/ops/protocol for protocol contract details.",
            "5) Check /api/ops/methods for WS method schemas and compatibility aliases.",
            "6) Check /api/ops/http-contracts for canonical HTTP request/response contracts.",
            "7) Check /api/ops/surfaces for full protocol surface discovery.",
            "8) Check /api/ops/framework-check for runtime contract consistency.",
            "9) Check /api/ops/readiness for go/no-go signal and startup/service drift.",
            "10) Check /api/config/contract for config inheritance and update schema.",
            "11) Check /api/config/default-template for bootstrap defaults and UI field groups.",
            "12) If chat errors occur, validate /api/config runtime and API key.",
            "13) If memory errors occur, verify Neo4j and memory flags.",
            "14) For automation calls, verify AUTOMATION__TOKEN header.",
        ],
    }

