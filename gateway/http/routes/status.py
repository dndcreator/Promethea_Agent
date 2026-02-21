from __future__ import annotations

from fastapi import APIRouter

from ..dispatcher import get_gateway_server


router = APIRouter()


@router.get("/status")
async def get_status():
    gateway_server = get_gateway_server()
    memory_status = bool(
        gateway_server.memory_service and gateway_server.memory_service.is_enabled()
    )
    conversation_ready = gateway_server.conversation_service is not None
    return {
        "status": "running",
        "conversation_ready": conversation_ready,
        "memory_active": memory_status,
    }


@router.get("/status/services")
async def get_services_status():
    gateway_server = get_gateway_server()
    health = gateway_server.get_services_health()
    overall = "healthy" if all(health.values()) else "degraded"
    return {"status": overall, "services": health}


@router.get("/status/routes")
async def get_gateway_routes():
    gateway_server = get_gateway_server()
    methods = sorted([str(k.value) for k in gateway_server._handlers.keys()])  # noqa: SLF001
    return {"status": "success", "gateway_methods": methods}


