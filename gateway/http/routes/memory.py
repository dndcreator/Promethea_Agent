from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from gateway.protocol import RequestType
from memory.session_scope import ensure_session_owned

from ..dispatcher import get_gateway_server, dispatch_gateway_method
from .auth import get_current_user_id


router = APIRouter()


def _get_runtime_components():
    gateway_server = get_gateway_server()
    message_manager = gateway_server.message_manager
    memory_service = gateway_server.memory_service
    if not message_manager:
        raise HTTPException(status_code=503, detail="Message manager not initialized")
    if not memory_service:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return message_manager, memory_service


def _ensure_user_session(session_id: str, user_id: str) -> None:
    message_manager, _ = _get_runtime_components()
    if not message_manager.get_session(session_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Session not found")


def _get_memory_connector():
    _, memory_service = _get_runtime_components()
    if not memory_service.is_enabled():
        raise HTTPException(status_code=503, detail="Memory system not enabled")
    memory_adapter = memory_service.memory_adapter
    if not memory_adapter or not memory_adapter.hot_layer:
        raise HTTPException(status_code=503, detail="Memory hot layer not available")
    return memory_adapter.hot_layer.connector


def _resolve_owned_memory_session(session_id: str, user_id: str) -> str:
    connector = _get_memory_connector()
    owned, resolved = ensure_session_owned(connector, session_id, user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Session memory not found")
    return resolved


@router.post("/memory/cluster/{session_id}")
async def cluster_session_memory(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_CLUSTER,
        {"session_id": session_id},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.get("/memory/concepts/{session_id}")
async def get_session_concepts(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        _ensure_user_session(session_id, user_id)
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)

        from memory import create_warm_layer_manager

        connector = _get_memory_connector()
        warm_layer = create_warm_layer_manager(connector)
        if not warm_layer:
            raise HTTPException(status_code=503, detail="Warm layer unavailable")
        concepts = warm_layer.get_concepts(scoped_session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "user_id": user_id,
            "memory_session_id": scoped_session_id,
            "concepts": concepts,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get concepts failed: {e}")


@router.post("/memory/summarize/{session_id}")
async def summarize_session(
    session_id: str,
    incremental: bool = False,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_SUMMARIZE,
        {"session_id": session_id, "incremental": incremental},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.get("/memory/summaries/{session_id}")
async def get_session_summaries(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        _ensure_user_session(session_id, user_id)
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)

        from memory import create_cold_layer_manager

        connector = _get_memory_connector()
        cold_layer = create_cold_layer_manager(connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="Cold layer unavailable")

        summaries = cold_layer.get_summaries(scoped_session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "user_id": user_id,
            "memory_session_id": scoped_session_id,
            "total_summaries": len(summaries),
            "summaries": summaries,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get summaries failed: {e}")


@router.get("/memory/summary/{summary_id}")
async def get_summary(
    summary_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        from memory import create_cold_layer_manager

        connector = _get_memory_connector()
        cold_layer = create_cold_layer_manager(connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="Cold layer unavailable")

        summary = cold_layer.get_summary_by_id(summary_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found")

        raw_session_id = str(summary.get("session_id") or "")
        owned, _ = ensure_session_owned(
            connector,
            raw_session_id,
            user_id,
        )
        if not owned:
            raise HTTPException(status_code=404, detail="Summary not found")

        return {
            "status": "success",
            "user_id": user_id,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get summary failed: {e}")


@router.get("/memory/graph/{session_id}")
async def get_memory_graph(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_GRAPH,
        {"session_id": session_id},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.post("/memory/decay/{session_id}")
async def apply_memory_decay(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_DECAY,
        {"session_id": session_id},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.post("/memory/cleanup/{session_id}")
async def cleanup_forgotten_memory(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_CLEANUP,
        {"session_id": session_id},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.get("/memory/forgetting/stats/{session_id}")
async def get_forgetting_stats(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        _ensure_user_session(session_id, user_id)
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)

        from memory import create_forgetting_manager

        connector = _get_memory_connector()
        forgetting_manager = create_forgetting_manager(connector)
        stats = forgetting_manager.get_forgetting_stats(scoped_session_id)

        return {
            "status": "success",
            "session_id": session_id,
            "user_id": user_id,
            "memory_session_id": scoped_session_id,
            **stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get forgetting stats failed: {e}")
        raise HTTPException(status_code=500, detail=f"Get forgetting stats failed: {e}")


