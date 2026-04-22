from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .. import state
from ..dispatcher import get_gateway_server
from ..user_file_store import user_file_store


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
        "memory_sync": (
            gateway_server.memory_service.get_sync_stats()
            if gateway_server.memory_service
            else {}
        ),
        "channels": len(gateway_server.channels),
    }
    metrics = state.metrics.get_stats()
    message_manager = getattr(gateway_server, "message_manager", None)
    sessions_current = 0
    sessions_pinned = 0
    if message_manager is not None:
        session_obj = getattr(message_manager, "session", None)
        if isinstance(session_obj, dict):
            sessions_current = len(session_obj)
            sessions_pinned = sum(1 for x in session_obj.values() if bool(getattr(x, "pinned", False)))
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    workflow_recovery = {"paused": 0, "failed": 0, "waiting_human": 0}
    if workflow_engine is not None and hasattr(workflow_engine, "list_runs"):
        try:
            runs = workflow_engine.list_runs(limit=500)
            if isinstance(runs, list):
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    status = str(run.get("status") or "").lower()
                    if status == "paused":
                        workflow_recovery["paused"] += 1
                    if status == "failed":
                        workflow_recovery["failed"] += 1
                    if status == "waiting_human":
                        workflow_recovery["waiting_human"] += 1
        except Exception:
            pass
    file_stats = user_file_store.get_global_stats()
    metrics["gateway"] = gateway_metrics
    metrics["personal"] = {
        "sessions_current": sessions_current,
        "sessions_pinned": sessions_pinned,
        "files_total": int(file_stats.get("total_files") or 0),
        "files_total_bytes": int(file_stats.get("total_bytes") or 0),
        "file_users": int(file_stats.get("total_users") or 0),
    }
    metrics["workflow_recovery"] = workflow_recovery
    return {"status": "success", "metrics": metrics}


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def get_prometheus_metrics():
    return state.metrics.to_prometheus_text()


