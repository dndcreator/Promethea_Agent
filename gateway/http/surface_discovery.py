from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from gateway.protocol import EventType, RequestType
from gateway.protocol_contracts import build_ws_method_contracts


def _route_stability(path: str, methods: list[str]) -> str:
    method_set = set(methods)
    if path == "/api/user/config":
        return "legacy"
    if path == "/api/config" and "POST" in method_set:
        return "compat"
    if path.startswith("/api/ops/") or path.startswith("/api/config/"):
        return "stable"
    if path.startswith("/api/chat") or path.startswith("/api/memory/"):
        return "stable"
    return "stable"


def collect_http_surface_from_routes(routes: Iterable[Any]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for route in routes:
        path = getattr(route, "path", "")
        if not isinstance(path, str) or not path.startswith("/api"):
            continue
        methods = sorted(
            method for method in (getattr(route, "methods", set()) or set())
            if method not in {"HEAD", "OPTIONS"}
        )
        rows.append(
            {
                "path": path,
                "methods": methods,
                "name": getattr(route, "name", None),
                "stability": _route_stability(path, methods),
            }
        )
    rows.sort(key=lambda item: (item["path"], ",".join(item["methods"])))
    return rows


def build_surface_payload(routes: Iterable[Any]) -> Dict[str, Any]:
    http_routes = collect_http_surface_from_routes(routes)
    ws_method_details = build_ws_method_contracts()
    ws_methods = [item["method"] for item in ws_method_details]
    ws_events = sorted(et.value for et in EventType)
    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "surfaces": {
            "http": {
                "namespace": "/api",
                "routes": http_routes,
                "count": len(http_routes),
            },
            "websocket": {
                "path": "/gateway/ws/{device_id}",
                "request_methods": ws_methods,
                "request_method_details": ws_method_details,
                "event_types": ws_events,
                "request_method_count": len(ws_methods),
                "event_type_count": len(ws_events),
            },
            "contracts": {
                "protocol": "/api/ops/protocol",
                "abstractions": "/api/ops/abstractions",
                "ws_methods": "/api/ops/methods",
                "http_contracts": "/api/ops/http-contracts",
                "framework_check": "/api/ops/framework-check",
                "readiness": "/api/ops/readiness",
                "governance": "/api/ops/governance",
                "config": "/api/config/contract",
                "config_default_template": "/api/config/default-template",
            },
            "stability_levels": {
                "stable": "recommended for long-term integrations",
                "compat": "supported compatibility surface; canonical alternative exists",
                "legacy": "deprecated compatibility surface",
            },
            "cli_reference": {
                "ops.capabilities": {"command": "promethea ops capabilities", "http": "GET /api/ops/capabilities"},
                "ops.abstractions": {"command": "promethea ops abstractions", "http": "GET /api/ops/abstractions"},
                "ops.protocol": {"command": "promethea ops protocol", "http": "GET /api/ops/protocol"},
                "ops.methods": {"command": "promethea ops methods", "http": "GET /api/ops/methods"},
                "ops.http_contracts": {"command": "promethea ops http-contracts", "http": "GET /api/ops/http-contracts"},
                "ops.framework_check": {"command": "promethea ops framework-check", "http": "GET /api/ops/framework-check"},
                "ops.readiness": {"command": "promethea ops readiness", "http": "GET /api/ops/readiness"},
                "ops.surfaces": {"command": "promethea ops surfaces", "http": "GET /api/ops/surfaces"},
                "ops.governance": {"command": "promethea ops governance", "http": "GET /api/ops/governance"},
                "config.contract": {"command": "promethea config contract", "http": "GET /api/config/contract"},
                "config.template": {"command": "promethea config template --view full", "http": "GET /api/config/default-template"},
                "config.update": {"command": "promethea config update --file patch.json", "http": "POST /api/config/update"},
                "config.effective": {"command": "promethea config effective --view full", "http": "GET /api/config/effective"},
                "config.ui_schema": {"command": "promethea config ui-schema --view both", "http": "GET /api/config/ui-schema"},
                "status.official_tools": {"command": "promethea status official-tools", "http": "GET /api/status/tools/official"},
            },
        },
    }
