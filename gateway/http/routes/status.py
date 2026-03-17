from __future__ import annotations

from fastapi import APIRouter

from gateway.tool_service import ToolService
from ..dispatcher import get_gateway_server


router = APIRouter()


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
    }


@router.get("/status/services")
async def get_services_status():
    gateway_server = get_gateway_server()
    health = gateway_server.get_services_health()
    overall = "healthy" if all(health.values()) else "degraded"
    return {"status": overall, "services": health}


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
async def get_gateway_routes():
    gateway_server = get_gateway_server()
    methods = sorted([str(k.value) for k in gateway_server._handlers.keys()])  # noqa: SLF001
    return {"status": "success", "gateway_methods": methods}


@router.get("/status/tools")
async def get_tools_status():
    gateway_server = get_gateway_server()
    if not gateway_server.tool_service:
        gateway_server.tool_service = ToolService(gateway_server.event_emitter)

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


