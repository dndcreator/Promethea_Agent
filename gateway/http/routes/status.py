from __future__ import annotations

from fastapi import APIRouter, Request

from gateway.official_tools import register_official_tools
from gateway.tool_service import ToolService
from .. import state
from ..dispatcher import get_gateway_server


router = APIRouter()


def _ensure_tool_service():
    gateway_server = get_gateway_server()
    if not gateway_server.tool_service:
        gateway_server.tool_service = ToolService(gateway_server.event_emitter)
    register_official_tools(
        tool_service=gateway_server.tool_service,
        workspace_service=getattr(gateway_server, "workspace_service", None),
        memory_service=getattr(gateway_server, "memory_service", None),
        message_manager=getattr(gateway_server, "message_manager", None),
        gateway_server=gateway_server,
    )
    return gateway_server


@router.get("/status")
async def get_status():
    gateway_server = get_gateway_server()
    memory_status = bool(
        gateway_server.memory_service and gateway_server.memory_service.is_enabled()
    )
    conversation_ready = gateway_server.conversation_service is not None
    memory_sync = (
        gateway_server.memory_service.get_sync_stats()
        if gateway_server.memory_service
        else {
            "enabled": False,
            "pending": 0,
            "queued": 0,
            "active": 0,
            "idle": True,
        }
    )
    reasoning = (
        gateway_server.reasoning_service.get_stats()
        if getattr(gateway_server, "reasoning_service", None)
        else {"enabled": False, "active_trees": 0}
    )
    return {
        "status": "running",
        "conversation_ready": conversation_ready,
        "memory_active": memory_status,
        "memory_sync": memory_sync,
        "reasoning": reasoning,
        "startup": dict(state.startup_report or {}),
    }


@router.get("/status/services")
async def get_services_status():
    gateway_server = get_gateway_server()
    health = gateway_server.get_services_health()
    failed = sorted([k for k, ok in health.items() if not bool(ok)])
    total = max(1, len(health))
    ok_count = total - len(failed)
    ratio = ok_count / total
    if ratio >= 0.99:
        overall = "healthy"
    elif ratio >= 0.5:
        overall = "degraded"
    else:
        overall = "unhealthy"
    recommendations = [
        {
            "component": name,
            "action": f"initialize {name} and verify runtime dependencies",
        }
        for name in failed
    ]
    return {
        "status": overall,
        "summary": {"total": total, "ok": ok_count, "failed": len(failed)},
        "services": health,
        "failed_services": failed,
        "recommendations": recommendations,
        "startup": dict(state.startup_report or {}),
    }


@router.get("/health/memory")
async def get_memory_health():
    gateway_server = get_gateway_server()
    memory_service = getattr(gateway_server, "memory_service", None)
    if memory_service is None:
        return {
            "status": "unavailable",
            "enabled": False,
            "configured_backend": None,
            "active_backend": None,
            "ready": False,
            "reason": "memory_service_not_initialized",
        }

    adapter = getattr(memory_service, "memory_adapter", None)
    configured_backend = (
        str(getattr(adapter, "store_backend", "") or "").strip().lower() if adapter else None
    )
    active_backend = None
    if adapter is not None:
        store = getattr(adapter, "store", None)
        if store is not None:
            active_backend = str(
                getattr(store, "backend_name", configured_backend) or configured_backend
            )
        elif getattr(adapter, "hot_layer", None) is not None:
            active_backend = "neo4j"

    enabled = bool(getattr(memory_service, "enabled", False))
    ready = bool(memory_service.is_enabled())
    sync = memory_service.get_sync_stats()
    status = "healthy" if ready else ("disabled" if not enabled else "degraded")
    reason = ""
    if not ready:
        if not enabled:
            reason = "memory_disabled_or_unavailable"
        elif configured_backend == "neo4j":
            reason = "neo4j_not_ready"
        else:
            reason = "backend_not_ready"

    return {
        "status": status,
        "enabled": enabled,
        "configured_backend": configured_backend,
        "active_backend": active_backend,
        "ready": ready,
        "sync": sync,
        "reason": reason,
    }


@router.get("/status/routes")
async def get_gateway_routes(request: Request):
    gateway_server = get_gateway_server()
    methods = sorted([str(k.value) for k in gateway_server._handlers.keys()])  # noqa: SLF001
    http_routes = []
    for route in request.app.routes:
        path = getattr(route, "path", "")
        if isinstance(path, str) and path.startswith("/api"):
            http_routes.append(path)
    http_routes = sorted(set(http_routes))
    return {
        "status": "success",
        "gateway_methods": methods,
        "http_routes": http_routes,
        "counts": {"gateway_methods": len(methods), "http_routes": len(http_routes)},
    }


@router.get("/status/tools")
async def get_tools_status():
    gateway_server = _ensure_tool_service()
    catalog = await gateway_server.tool_service.get_tool_catalog()
    by_type: dict[str, int] = {}
    for item in catalog:
        tool_type = str(item.get("tool_type", "unknown") or "unknown")
        by_type[tool_type] = by_type.get(tool_type, 0) + 1

    return {
        "status": "success",
        "total": len(catalog),
        "by_type": by_type,
        "tools": catalog,
    }


@router.get("/status/tools/official")
async def get_official_tools_status():
    gateway_server = _ensure_tool_service()
    registered = getattr(gateway_server.tool_service, "_registered_tools", {}) or {}
    items = []
    domains: dict[str, int] = {}
    for tool_id, tool in registered.items():
        if not bool(getattr(tool, "official", False)):
            continue
        domain = str(getattr(tool, "official_domain", "misc") or "misc")
        domains[domain] = domains.get(domain, 0) + 1
        items.append(
            {
                "tool_id": tool_id,
                "name": str(getattr(tool, "name", tool_id)),
                "description": str(getattr(tool, "description", "")),
                "domain": domain,
            }
        )
    items.sort(key=lambda x: (x["domain"], x["tool_id"]))
    return {
        "status": "success",
        "total": len(items),
        "by_domain": domains,
        "tools": items,
    }


