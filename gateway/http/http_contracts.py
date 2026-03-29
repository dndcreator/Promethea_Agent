from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from .surface_discovery import collect_http_surface_from_routes


def _core_contracts() -> List[Dict[str, Any]]:
    return [
        {
            "id": "chat.turn",
            "path": "/api/chat",
            "method": "POST",
            "domain": "conversation",
            "stability": "stable",
            "auth_required": True,
            "request": {
                "message": "string",
                "session_id": "optional<string>",
                "stream": "bool",
                "requested_mode": "optional<string>",
                "requested_skill": "optional<string>",
            },
            "response": {
                "status": "success|error",
                "response": "string",
                "session_id": "string",
            },
        },
        {
            "id": "chat.confirm",
            "path": "/api/chat/confirm",
            "method": "POST",
            "domain": "conversation",
            "stability": "stable",
            "auth_required": True,
            "request": {
                "session_id": "string",
                "tool_call_id": "string",
                "action": "approve|reject",
            },
            "response": {"status": "success|error"},
        },
        {
            "id": "config.update",
            "path": "/api/config/update",
            "method": "POST",
            "domain": "config",
            "stability": "stable",
            "auth_required": True,
            "request": {
                "config": "object",
                "options.hot_apply": "bool",
                "validate": "bool",
            },
            "compat_aliases": {
                "config_data": "config",
                "hot_reload": "options.hot_apply",
                "hot_apply": "options.hot_apply",
                "validate_config": "validate",
            },
            "response": {
                "success": "bool",
                "message": "string",
                "config": "object",
                "hot_apply": {
                    "requested": "bool",
                    "success": "bool",
                    "message": "optional<string>",
                },
            },
        },
        {
            "id": "config.contract",
            "path": "/api/config/contract",
            "method": "GET",
            "domain": "config",
            "stability": "stable",
            "auth_required": True,
            "request": {},
            "response": {"status": "success", "contract": "object"},
        },
        {
            "id": "config.default_template",
            "path": "/api/config/default-template",
            "method": "GET",
            "domain": "config",
            "stability": "stable",
            "auth_required": True,
            "request": {"view": "basic|full", "raw": "bool"},
            "response": {"status": "success", "template": "object"},
        },
        {
            "id": "memory.entries.list",
            "path": "/api/memory/entries",
            "method": "GET",
            "domain": "memory",
            "stability": "stable",
            "auth_required": True,
            "request": {
                "scope": "all|session|project|identity|constraints|preferences",
                "session_id": "optional<string>",
                "q": "optional<string>",
                "memory_types": "optional<string>",
                "limit": "int",
                "offset": "int",
            },
            "response": {"status": "success", "entries": "array", "total": "int"},
        },
        {
            "id": "memory.entries.create",
            "path": "/api/memory/entries",
            "method": "POST",
            "domain": "memory",
            "stability": "stable",
            "auth_required": True,
            "request": {"content": "string", "memory_type": "string", "session_id": "optional<string>"},
            "response": {"status": "success", "entry": "object"},
        },
        {
            "id": "memory.graph",
            "path": "/api/memory/graph",
            "method": "GET",
            "domain": "memory",
            "stability": "stable",
            "auth_required": True,
            "request": {},
            "response": {"status": "success", "nodes": "array", "edges": "array"},
        },
        {
            "id": "workflow.start",
            "path": "/api/workflow/start",
            "method": "POST",
            "domain": "workflow",
            "stability": "stable",
            "auth_required": True,
            "request": {"workflow_id": "string", "input": "optional<object>"},
            "response": {"status": "success", "run": "object"},
        },
        {
            "id": "workflow.status",
            "path": "/api/workflow/run/{workflow_run_id}",
            "method": "GET",
            "domain": "workflow",
            "stability": "stable",
            "auth_required": True,
            "request": {"workflow_run_id": "string"},
            "response": {"status": "success", "run": "object"},
        },
        {
            "id": "skills.catalog",
            "path": "/api/skills/catalog",
            "method": "GET",
            "domain": "tooling",
            "stability": "stable",
            "auth_required": True,
            "request": {},
            "response": {"status": "success", "skills": "array"},
        },
        {
            "id": "ops.protocol",
            "path": "/api/ops/protocol",
            "method": "GET",
            "domain": "ops",
            "stability": "stable",
            "auth_required": False,
            "request": {},
            "response": {"status": "success", "protocol": "object"},
        },
        {
            "id": "ops.methods",
            "path": "/api/ops/methods",
            "method": "GET",
            "domain": "ops",
            "stability": "stable",
            "auth_required": False,
            "request": {},
            "response": {"status": "success", "methods": "array"},
        },
        {
            "id": "ops.http_contracts",
            "path": "/api/ops/http-contracts",
            "method": "GET",
            "domain": "ops",
            "stability": "stable",
            "auth_required": False,
            "request": {},
            "response": {"status": "success", "contracts": "array"},
        },
        {
            "id": "ops.framework_check",
            "path": "/api/ops/framework-check",
            "method": "GET",
            "domain": "ops",
            "stability": "stable",
            "auth_required": False,
            "request": {},
            "response": {"status": "success", "ok": "bool", "checks": "object"},
        },
        {
            "id": "ops.surfaces",
            "path": "/api/ops/surfaces",
            "method": "GET",
            "domain": "ops",
            "stability": "stable",
            "auth_required": False,
            "request": {},
            "response": {"status": "success", "surfaces": "object"},
        },
    ]


def _infer_domain(path: str) -> str:
    if path.startswith("/api/chat") or path.startswith("/api/followup") or path.startswith("/api/sessions"):
        return "conversation"
    if path.startswith("/api/config"):
        return "config"
    if path.startswith("/api/memory"):
        return "memory"
    if path.startswith("/api/workflow"):
        return "workflow"
    if path.startswith("/api/security"):
        return "security"
    if path.startswith("/api/skills"):
        return "skills"
    if path.startswith("/api/voice"):
        return "voice"
    if path.startswith("/api/automation"):
        return "automation"
    if path.startswith("/api/ops"):
        return "ops"
    if path.startswith("/api/auth") or path.startswith("/api/user"):
        return "auth"
    if path.startswith("/api/status") or path.startswith("/api/health") or path.startswith("/api/metrics") or path.startswith("/api/doctor"):
        return "status"
    return "system"


def _infer_auth_required(path: str) -> bool:
    if path in {"/api/status", "/api/metrics", "/api/auth/login", "/api/auth/register"}:
        return False
    if path.startswith("/api/ops/"):
        return False
    if path.startswith("/api/automation/"):
        return False
    return True


def _auto_id(method: str, path: str) -> str:
    body = path.removeprefix("/api/").replace("/", ".").replace("{", "").replace("}", "").replace("-", "_")
    body = body.strip(".") or "root"
    return f"auto.{method.lower()}.{body}"


def _merge_contracts(
    *,
    core: List[Dict[str, Any]],
    routes: Iterable[Any] | None,
) -> List[Dict[str, Any]]:
    core_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {
        (str(item["method"]).upper(), str(item["path"])): dict(item) for item in core
    }
    if routes is None:
        out = list(core_by_key.values())
        out.sort(key=lambda item: (item["path"], item["method"], item["id"]))
        return out

    out: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in collect_http_surface_from_routes(routes):
        path = str(row.get("path") or "")
        stability = str(row.get("stability") or "stable")
        for method in row.get("methods") or []:
            m = str(method).upper()
            key = (m, path)
            if key in core_by_key:
                item = dict(core_by_key[key])
            else:
                item = {
                    "id": _auto_id(m, path),
                    "path": path,
                    "method": m,
                    "domain": _infer_domain(path),
                    "stability": stability,
                    "auth_required": _infer_auth_required(path),
                    "request": {},
                    "response": {"status": "success|error"},
                }
            base_id = str(item["id"])
            unique_id = base_id
            suffix = 2
            while unique_id in seen_ids:
                unique_id = f"{base_id}_{suffix}"
                suffix += 1
            item["id"] = unique_id
            seen_ids.add(unique_id)
            out.append(item)

    out.sort(key=lambda item: (item["path"], item["method"], item["id"]))
    return out


def build_http_contracts(routes: Iterable[Any] | None = None) -> List[Dict[str, Any]]:
    return _merge_contracts(core=_core_contracts(), routes=routes)


def index_http_contracts(contracts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {item["id"]: item for item in contracts}
