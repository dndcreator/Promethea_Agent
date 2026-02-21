from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .. import state
from ..dispatcher import get_gateway_server


router = APIRouter()


@router.get("/metrics")
async def get_metrics():
    """Get runtime metrics."""
    gateway_server = get_gateway_server()
    gateway_metrics = {
        "connections": gateway_server.connection_manager.get_active_count(),
        "conversation_processing": (
            gateway_server.conversation_service.get_processing_stats()
            if gateway_server.conversation_service
            else {}
        ),
        "channels": len(gateway_server.channels),
    }
    metrics = state.metrics.get_stats()
    metrics["gateway"] = gateway_metrics
    return {"status": "success", "metrics": metrics}


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def get_prometheus_metrics():
    return state.metrics.to_prometheus_text()


