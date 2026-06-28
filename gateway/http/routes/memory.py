from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from gateway.protocol import RequestType
from ..dispatcher import get_gateway_server, dispatch_gateway_method
from .auth import get_current_user_id


router = APIRouter()


class MemoryEntryCreateRequest(BaseModel):
    content: str
    memory_type: str = "preference"
    session_id: Optional[str] = None
    source_layer: Optional[str] = None


class MemoryEntryUpdateRequest(BaseModel):
    content: Optional[str] = None
    memory_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MemoryProposalDecisionRequest(BaseModel):
    action: str = Field(description="confirm_write | confirm_write_keep_existing | ignore_once | reduce_similar")


def _get_runtime_components():
    gateway_server = get_gateway_server()
    memory_service = gateway_server.memory_service
    if not memory_service:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return memory_service


def _resolve_owned_memory_session(session_id: str, user_id: str) -> str:
    memory_service = _get_runtime_components()
    session_check = memory_service.ensure_session_access(session_id=session_id, user_id=user_id)
    if not session_check.get("ok"):
        reason = str(session_check.get("reason") or "")
        if reason == "message_manager_unavailable":
            raise HTTPException(status_code=503, detail="Message manager not initialized")
        raise HTTPException(status_code=404, detail="Session not found")
    resolved = memory_service.resolve_owned_memory_session(session_id=session_id, user_id=user_id)
    if not resolved.get("ok"):
        reason = str(resolved.get("reason") or "")
        if reason in {"memory_not_enabled", "hot_layer_unavailable"}:
            raise HTTPException(status_code=503, detail="Memory system not enabled")
        raise HTTPException(status_code=404, detail="Session memory not found")
    return str(resolved.get("memory_session_id") or "")


@router.post("/memory/cluster/{session_id}")
async def cluster_session_memory(
    session_id: str,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_CLUSTER,
        {"session_id": session_id},
        user_id=user_id,
        request=raw_request,
    )
    return {"status": "success", **payload}


@router.get("/memory/concepts/{session_id}")
async def get_session_concepts(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)
        memory_service = _get_runtime_components()
        result = memory_service.get_session_concepts(memory_session_id=scoped_session_id)
        if not result.get("ok"):
            reason = str(result.get("reason") or "")
            if reason == "warm_layer_unavailable":
                raise HTTPException(status_code=503, detail="Warm layer unavailable")
            raise RuntimeError(reason or "get_concepts_failed")
        concepts = result.get("concepts") or []
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
    raw_request: Request,
    incremental: bool = False,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_SUMMARIZE,
        {"session_id": session_id, "incremental": incremental},
        user_id=user_id,
        request=raw_request,
    )
    return {"status": "success", **payload}


@router.get("/memory/summaries/{session_id}")
async def get_session_summaries(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)
        memory_service = _get_runtime_components()
        result = memory_service.get_session_summaries(memory_session_id=scoped_session_id)
        if not result.get("ok"):
            reason = str(result.get("reason") or "")
            if reason == "cold_layer_unavailable":
                raise HTTPException(status_code=503, detail="Cold layer unavailable")
            raise RuntimeError(reason or "get_summaries_failed")
        summaries = result.get("summaries") or []
        return {
            "status": "success",
            "session_id": session_id,
            "user_id": user_id,
            "memory_session_id": scoped_session_id,
            "total_summaries": int(result.get("total_summaries") or len(summaries)),
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
        memory_service = _get_runtime_components()
        result = memory_service.get_summary_for_user(summary_id=summary_id, user_id=user_id)
        if not result.get("ok"):
            reason = str(result.get("reason") or "")
            if reason == "cold_layer_unavailable":
                raise HTTPException(status_code=503, detail="Cold layer unavailable")
            if reason == "summary_not_found":
                raise HTTPException(status_code=404, detail="Summary not found")
            raise RuntimeError(reason or "get_summary_failed")
        summary = result.get("summary") or {}
        return {
            "status": "success",
            "user_id": user_id,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get summary failed: {e}")


@router.get("/memory/graph")
async def get_memory_graph_global(
    user_id: str = Depends(get_current_user_id),
):
    """
    Return user-scoped full memory graph across all sessions.
    """
    try:
        memory_service = _get_runtime_components()
        result = memory_service.get_graph_global_for_user(user_id=user_id)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("reason") or "graph_global_failed"))
        return {
            "status": "success",
            "user_id": user_id,
            "graph_available": bool(result.get("graph_available", False)),
            "graph_mode": result.get("graph_mode", "none"),
            "graph_semantics": result.get("graph_semantics", "none"),
            "semantic_graph_available": bool(result.get("semantic_graph_available", False)),
            "nodes": result.get("nodes") or [],
            "edges": result.get("edges") or [],
            "stats": result.get("stats") or {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get global memory graph failed: {e}")


@router.get("/memory/graph/search")
async def search_memory_graph(
    q: str = "",
    depth: int = 1,
    limit_nodes: int = 80,
    limit_edges: int = 160,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    result = memory_service.search_graph_for_user(
        user_id=user_id,
        query=q,
        depth=depth,
        limit_nodes=limit_nodes,
        limit_edges=limit_edges,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=str(result.get("reason") or "graph_search_failed"))
    return {
        "status": "success",
        "user_id": user_id,
        "graph_available": bool(result.get("graph_available", False)),
        "graph_mode": result.get("graph_mode", "none"),
        "graph_semantics": result.get("graph_semantics", "none"),
        "semantic_graph_available": bool(result.get("semantic_graph_available", False)),
        "query": result.get("query") or q,
        "search_mode": result.get("search_mode") or "overview",
        "seed_node_ids": result.get("seed_node_ids") or [],
        "nodes": result.get("nodes") or [],
        "edges": result.get("edges") or [],
        "stats": result.get("stats") or {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
    }


@router.get("/memory/graph/{session_id}")
async def get_memory_graph(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        memory_service = _get_runtime_components()
        prebuilt = memory_service.get_graph_for_session(session_id=session_id, user_id=user_id)
        if prebuilt.get("ok") and prebuilt.get("handled"):
            return {
                "status": "success",
                "session_id": session_id,
                "graph_available": bool(prebuilt.get("graph_available", False)),
                "graph_mode": prebuilt.get("graph_mode", "none"),
                "graph_semantics": prebuilt.get("graph_semantics", "none"),
                "semantic_graph_available": bool(prebuilt.get("semantic_graph_available", False)),
                "nodes": prebuilt.get("nodes") or [],
                "edges": prebuilt.get("edges") or [],
                "stats": prebuilt.get("stats") or {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }
        payload = await dispatch_gateway_method(
            RequestType.MEMORY_GRAPH,
            {"session_id": session_id},
            user_id=user_id,
        )
        return {
            "status": "success",
            "graph_available": True,
            "graph_mode": "neo4j",
            "graph_semantics": "semantic",
            "semantic_graph_available": True,
            **payload,
        }
    except HTTPException as e:
        # Fresh sessions may not have memory nodes yet. Keep UI stable with empty graph.
        if e.status_code == 404:
            return {
                "status": "success",
                "session_id": session_id,
                "graph_available": True,
                "graph_mode": "neo4j",
                "graph_semantics": "semantic",
                "semantic_graph_available": True,
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }
        raise


@router.get("/memory/capabilities")
async def get_memory_capabilities(user_id: str = Depends(get_current_user_id)):
    memory_service = _get_runtime_components()
    payload = memory_service.get_capabilities_snapshot()
    if not payload.get("ok"):
        raise HTTPException(status_code=503, detail="Memory adapter unavailable")
    return {
        "status": "success",
        "user_id": user_id,
        "enabled": bool(payload.get("enabled", False)),
        "capabilities": payload.get("capabilities") or {},
    }


@router.get("/memory/entries")
async def list_memory_entries(
    scope: str = "all",
    session_id: Optional[str] = None,
    memory_types: Optional[str] = None,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    include_archived: bool = False,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    result = memory_service.list_entries(
        user_id=user_id,
        scope=scope,
        session_id=session_id,
        memory_types=memory_types,
        query=q,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail="Memory system not enabled")
    return {
        "status": "success",
        "user_id": user_id,
        "entries": result.get("entries") or [],
        "total": int(result.get("total") or 0),
    }


@router.get("/memory/search")
async def search_memory_entries(
    q: str,
    limit: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    result = memory_service.search_entries(
        user_id=user_id,
        query=q,
        limit=limit,
    )
    if not result.get("ok"):
        reason = str(result.get("reason") or "search_failed")
        if reason == "query_required":
            raise HTTPException(status_code=400, detail="q is required")
        raise HTTPException(status_code=503, detail="Memory system not enabled")
    return {
        "status": "success",
        "user_id": user_id,
        "query": result.get("query") or q,
        "entries": result.get("entries") or [],
        "total": int(result.get("total") or 0),
    }


@router.post("/memory/entries")
async def create_memory_entry(
    request: MemoryEntryCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    result = memory_service.create_entry(
        user_id=user_id,
        content=request.content,
        memory_type=request.memory_type,
        session_id=request.session_id,
        source_layer=request.source_layer,
    )
    if not result.get("ok"):
        if str(result.get("reason") or "") == "content_required":
            raise HTTPException(status_code=400, detail="content is required")
        if str(result.get("reason") or "") == "memory_not_enabled":
            raise HTTPException(status_code=503, detail="Memory system not enabled")
        raise HTTPException(status_code=500, detail="failed to create memory entry")
    return {"status": "success", "created": True}


@router.patch("/memory/entries/{memory_id}")
async def update_memory_entry(
    memory_id: str,
    request: MemoryEntryUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    res = memory_service.update_entry(
        user_id=user_id,
        memory_id=memory_id,
        content=request.content,
        memory_type=request.memory_type,
        metadata=request.metadata,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=str(res.get("reason") or "update_failed"))
    return {"status": "success", **res}


@router.delete("/memory/entries/{memory_id}")
async def delete_memory_entry(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    res = memory_service.delete_entry(user_id=user_id, memory_id=memory_id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=str(res.get("reason") or "not_found"))
    return {"status": "success", **res}


@router.get("/memory/write-decisions")
async def list_memory_write_decisions(
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision: Optional[str] = None,
    limit: int = 100,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    rows = memory_service.list_write_decisions(
        user_id=user_id,
        session_id=session_id,
        trace_id=trace_id,
        decision=decision,
        limit=limit,
    )
    return {"status": "success", "user_id": user_id, "events": rows, "total": len(rows)}


@router.get("/memory/write-proposals")
async def list_memory_write_proposals(
    status: str = "pending",
    limit: int = 100,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    rows = memory_service.list_write_proposals(user_id=user_id, status=status, limit=limit)
    return {"status": "success", "user_id": user_id, "proposals": rows, "total": len(rows)}


@router.post("/memory/write-proposals/{proposal_id}/decision")
async def decide_memory_write_proposal(
    proposal_id: str,
    request: MemoryProposalDecisionRequest,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    result = await memory_service.resolve_write_proposal(
        proposal_id=proposal_id,
        user_id=user_id,
        action=request.action,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=str(result.get("reason") or "resolve_failed"))
    return {"status": "success", **result}


@router.get("/memory/dev/dashboard")
async def get_memory_dev_dashboard(
    session_id: Optional[str] = None,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
):
    memory_service = _get_runtime_components()
    stats = memory_service.build_dev_dashboard(user_id=user_id, session_id=session_id, limit=limit)
    return {
        "status": "success",
        "user_id": user_id,
        "session_id": session_id,
        "write": stats.get("write") or {},
        "recall": stats.get("recall") or {},
    }


@router.post("/memory/decay/{session_id}")
async def apply_memory_decay(
    session_id: str,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_DECAY,
        {"session_id": session_id},
        user_id=user_id,
        request=raw_request,
    )
    return {"status": "success", **payload}


@router.post("/memory/cleanup/{session_id}")
async def cleanup_forgotten_memory(
    session_id: str,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_CLEANUP,
        {"session_id": session_id},
        user_id=user_id,
        request=raw_request,
    )
    return {"status": "success", **payload}


@router.get("/memory/forgetting/stats/{session_id}")
async def get_forgetting_stats(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        scoped_session_id = _resolve_owned_memory_session(session_id, user_id)
        memory_service = _get_runtime_components()
        result = memory_service.get_forgetting_stats(memory_session_id=scoped_session_id)
        if not result.get("ok"):
            reason = str(result.get("reason") or "")
            if reason in {"memory_not_enabled", "hot_layer_unavailable"}:
                raise HTTPException(status_code=503, detail="Memory system not enabled")
            raise RuntimeError(reason or "get_forgetting_stats_failed")
        stats = result.get("stats") or {}
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



@router.get("/memory/recall/runs")
async def get_memory_recall_runs(
    session_id: str | None = None,
    trace_id: str | None = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_RECALL_RUNS,
        {"session_id": session_id, "trace_id": trace_id, "limit": limit},
        user_id=user_id,
    )
    return {"status": "success", **payload}


@router.get("/memory/recall/{target_request_id}")
async def inspect_memory_recall_run(
    target_request_id: str,
    user_id: str = Depends(get_current_user_id),
):
    payload = await dispatch_gateway_method(
        RequestType.MEMORY_RECALL_INSPECT,
        {"target_request_id": target_request_id},
        user_id=user_id,
    )
    return {"status": "success", **payload}
