from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .protocol import (
    AgentCallParams,
    ChatConfirmParams,
    ChatParams,
    ConfigSwitchModelParams,
    ConfigUpdateParams,
    FollowupParams,
    MemoryClusterParams,
    MemoryQueryParams,
    MemorySummarizeParams,
    RequestType,
    SendMessageParams,
    SessionParams,
)


def _request_model_map() -> Dict[RequestType, Type[BaseModel]]:
    return {
        RequestType.SEND: SendMessageParams,
        RequestType.AGENT: AgentCallParams,
        RequestType.MEMORY_QUERY: MemoryQueryParams,
        RequestType.FOLLOWUP: FollowupParams,
        RequestType.CHAT: ChatParams,
        RequestType.CHAT_CONFIRM: ChatConfirmParams,
        RequestType.MEMORY_CLUSTER: MemoryClusterParams,
        RequestType.MEMORY_SUMMARIZE: MemorySummarizeParams,
        RequestType.SESSION_DETAIL: SessionParams,
        RequestType.SESSION_DELETE: SessionParams,
        RequestType.MEMORY_GRAPH: SessionParams,
        RequestType.MEMORY_DECAY: SessionParams,
        RequestType.MEMORY_CLEANUP: SessionParams,
        RequestType.CONFIG_UPDATE: ConfigUpdateParams,
        RequestType.CONFIG_SWITCH_MODEL: ConfigSwitchModelParams,
    }


def _domain_for_method(method: RequestType) -> str:
    value = method.value
    if value.startswith("memory."):
        return "memory"
    if value.startswith("workflow."):
        return "workflow"
    if value.startswith("config."):
        return "config"
    if value.startswith("mcp.") or value.startswith("tool"):
        return "tooling"
    if value.startswith("workspace."):
        return "workspace"
    if value.startswith("computer."):
        return "computer"
    if value.startswith("session"):
        return "sessions"
    if value.startswith("chat") or value in {"followup", "send", "agent"}:
        return "conversation"
    return "system"


def _stability_for_method(method: RequestType) -> str:
    value = method.value
    if value in {"send", "agent"}:
        return "compat"
    return "stable"


def build_ws_method_contracts() -> List[Dict[str, Any]]:
    model_map = _request_model_map()
    rows: List[Dict[str, Any]] = []
    for method in sorted(RequestType, key=lambda item: item.value):
        model: Optional[Type[BaseModel]] = model_map.get(method)
        required: List[str] = []
        properties: Dict[str, Any] = {}
        if model is not None:
            schema = model.model_json_schema()
            required = list(schema.get("required", []))
            properties = dict(schema.get("properties", {}))

        aliases: Dict[str, str] = {}
        if method == RequestType.CONFIG_UPDATE:
            aliases = {
                "config_data": "config",
                "hot_reload": "options.hot_apply",
                "hot_apply": "options.hot_apply",
                "validate_config": "validate",
            }

        rows.append(
            {
                "method": method.value,
                "domain": _domain_for_method(method),
                "stability": _stability_for_method(method),
                "params_model": model.__name__ if model else None,
                "required_fields": required,
                "properties": properties,
                "aliases": aliases,
            }
        )
    return rows


def build_domain_contracts() -> Dict[str, Any]:
    ws_rows = build_ws_method_contracts()
    ws_by_domain: Dict[str, List[str]] = {}
    for row in ws_rows:
        domain = str(row.get("domain") or "system")
        method = str(row.get("method") or "")
        if not method:
            continue
        ws_by_domain.setdefault(domain, []).append(method)
    for key in list(ws_by_domain.keys()):
        ws_by_domain[key] = sorted(set(ws_by_domain[key]))

    return {
        "conversation": {
            "http": ["/api/chat", "/api/chat/confirm", "/api/followup"],
            "ws_methods": ws_by_domain.get("conversation", []),
            "canonical_request": {"message": "string", "session_id": "optional<string>", "stream": "bool"},
            "canonical_response": {"status": "success|error", "response": "string", "session_id": "string"},
        },
        "config": {
            "http": ["/api/config/update", "/api/config/contract", "/api/config/default-template"],
            "ws_methods": ws_by_domain.get("config", []),
            "canonical_update": {"config": "object", "options": {"hot_apply": "bool"}, "validate": "bool"},
            "compat_aliases": {
                "config_data": "config",
                "hot_reload": "options.hot_apply",
                "hot_apply": "options.hot_apply",
                "validate_config": "validate",
            },
        },
        "memory": {
            "http": ["/api/memory/entries", "/api/memory/graph", "/api/memory/recall/runs"],
            "ws_methods": ws_by_domain.get("memory", []),
            "notes": "session ownership and namespace isolation are enforced by runtime services.",
        },
        "workflow": {
            "http": ["/api/workflow/define", "/api/workflow/start", "/api/workflow/run/{workflow_run_id}"],
            "ws_methods": ws_by_domain.get("workflow", []),
            "notes": "workflow supports resumable runs and human-approval checkpoints.",
        },
        "tooling": {
            "http": ["/api/status/tools", "/api/skills/catalog", "/api/skills/activate"],
            "ws_methods": ws_by_domain.get("tooling", []),
            "notes": "tool execution must respect policy and emits auditable lifecycle events.",
        },
        "workspace": {
            "http": [],
            "ws_methods": ws_by_domain.get("workspace", []),
            "notes": "workspace artifact operations are protocol-first and primarily exposed via WS/dispatcher.",
        },
        "computer": {
            "http": [],
            "ws_methods": ws_by_domain.get("computer", []),
            "notes": "computer-control capabilities are routed through protocol handlers.",
        },
        "sessions": {
            "http": ["/api/sessions", "/api/sessions/{session_id}"],
            "ws_methods": ws_by_domain.get("sessions", []),
            "notes": "session metadata and lifecycle are accessible from both HTTP and WS surfaces.",
        },
        "system": {
            "http": ["/api/status", "/api/status/services", "/api/status/routes"],
            "ws_methods": ws_by_domain.get("system", []),
            "notes": "health/system methods remain lightweight compatibility surfaces.",
        },
    }
