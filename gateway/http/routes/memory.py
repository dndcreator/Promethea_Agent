from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from gateway.protocol import RequestType
from memory.session_scope import ensure_session_owned, user_node_id, scoped_session_id

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
    action: str = Field(description="confirm_write | ignore_once | reduce_similar")


def _get_runtime_components():
    gateway_server = get_gateway_server()
    message_manager = gateway_server.message_manager
    memory_service = gateway_server.memory_service
    if not message_manager:
        raise HTTPException(status_code=503, detail="Message manager not initialized")
    if not memory_service:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return message_manager, memory_service


def _get_memory_adapter():
    _, memory_service = _get_runtime_components()
    adapter = getattr(memory_service, "memory_adapter", None)
    if not adapter:
        raise HTTPException(status_code=503, detail="Memory adapter unavailable")
    return adapter


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


@router.get("/memory/graph")
async def get_memory_graph_global(
    user_id: str = Depends(get_current_user_id),
):
    """
    Return user-scoped full memory graph across all sessions.
    """
    try:
        _, memory_service = _get_runtime_components()
        adapter = getattr(memory_service, "memory_adapter", None)
        if adapter and str(getattr(adapter, "store_backend", "")).strip().lower() == "sqlite_graph":
            snapshot = adapter.export_mef(user_id=user_id)
            nodes_raw = snapshot.get("nodes") or []
            edges_raw = snapshot.get("edges") or []
            nodes = []
            for n in nodes_raw:
                nodes.append(
                    {
                        "id": n.get("id"),
                        "type": str(n.get("node_type") or n.get("type") or "").lower(),
                        "content": n.get("content", ""),
                        "layer": 1 if str(n.get("node_type") or "") == "token" else 0,
                        "importance": n.get("importance", 0.5),
                        "access_count": 0,
                        "created_at": n.get("created_at"),
                        "role": "",
                        "memory_type": "",
                        "memory_source": "sqlite_graph",
                    }
                )
            edges = [
                {
                    "source": e.get("src_node_id") or e.get("source"),
                    "target": e.get("dst_node_id") or e.get("target"),
                    "type": e.get("edge_type") or e.get("type") or "",
                    "weight": e.get("weight", 1.0),
                }
                for e in edges_raw
            ]
            return {
                "status": "success",
                "user_id": user_id,
                "graph_available": True,
                "graph_mode": "sqlite_graph",
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "layers": {
                        "hot": len([x for x in nodes if x.get("layer") == 0]),
                        "warm": len([x for x in nodes if x.get("layer") == 1]),
                        "cold": len([x for x in nodes if x.get("layer") == 2]),
                    },
                },
            }
        if adapter and str(getattr(adapter, "store_backend", "")).strip().lower() == "flat_memory":
            return {
                "status": "success",
                "user_id": user_id,
                "graph_available": False,
                "graph_mode": "none",
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }

        connector = _get_memory_connector()
        uid = user_node_id(user_id)

        nodes_query = """
        MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)
        OPTIONAL MATCH (m:Message)-[:PART_OF_SESSION]->(s)
        OPTIONAL MATCH (n)-[:FROM_MESSAGE]->(m)
        OPTIONAL MATCH (c:Concept)-[:PART_OF_SESSION]->(s)
        OPTIONAL MATCH (sum:Summary)
        WHERE EXISTS { MATCH (sum)-[rel]->(s) WHERE type(rel) = 'SUMMARIZES' }
        WITH collect(DISTINCT m) + collect(DISTINCT n) + collect(DISTINCT c) + collect(DISTINCT sum) AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        RETURN node.id AS id, labels(node)[0] AS type, node.content AS content,
               node.layer AS layer, node.importance AS importance,
               node.access_count AS access_count, node.created_at AS created_at,
               node.role AS role, node.memory_type AS memory_type, node.memory_source AS memory_source
        """

        edges_query = """
        MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)
        OPTIONAL MATCH (m:Message)-[:PART_OF_SESSION]->(s)
        OPTIONAL MATCH (n)-[:FROM_MESSAGE]->(m)
        OPTIONAL MATCH (c:Concept)-[:PART_OF_SESSION]->(s)
        OPTIONAL MATCH (sum:Summary)
        WHERE EXISTS { MATCH (sum)-[rel]->(s) WHERE type(rel) = 'SUMMARIZES' }
        WITH collect(DISTINCT m) + collect(DISTINCT n) + collect(DISTINCT c) + collect(DISTINCT sum) AS all_nodes
        UNWIND all_nodes AS node
        WITH collect(DISTINCT node.id) AS node_ids
        MATCH (a)-[r]->(b)
        WHERE a.id IN node_ids AND b.id IN node_ids
        RETURN a.id AS source, b.id AS target, type(r) AS type, r.weight AS weight
        """

        params = {"user_node_id": uid}
        nodes_raw = connector.query(nodes_query, params)
        edges_raw = connector.query(edges_query, params)

        nodes = [
            {
                "id": n.get("id"),
                "type": (n.get("type", "") or "").lower(),
                "content": n.get("content", ""),
                "layer": n.get("layer", 0),
                "importance": n.get("importance", 0.5),
                "access_count": n.get("access_count", 0),
                "created_at": n.get("created_at"),
                "role": n.get("role", ""),
                "memory_type": n.get("memory_type", ""),
                "memory_source": n.get("memory_source", ""),
            }
            for n in nodes_raw
        ]
        edges = [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "type": e.get("type", ""),
                "weight": e.get("weight", 1.0),
            }
            for e in edges_raw
        ]

        layer_counts = {"hot": 0, "warm": 0, "cold": 0}
        for node in nodes:
            layer = node.get("layer", 0)
            if layer == 0:
                layer_counts["hot"] += 1
            elif layer == 1:
                layer_counts["warm"] += 1
            elif layer == 2:
                layer_counts["cold"] += 1

        return {
            "status": "success",
            "user_id": user_id,
            "graph_available": True,
            "graph_mode": "neo4j",
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "layers": layer_counts,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get global memory graph failed: {e}")


@router.get("/memory/graph/{session_id}")
async def get_memory_graph(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        _, memory_service = _get_runtime_components()
        adapter = getattr(memory_service, "memory_adapter", None)
        if adapter and str(getattr(adapter, "store_backend", "")).strip().lower() == "sqlite_graph":
            scoped_sid = scoped_session_id(session_id, user_id)
            snapshot = adapter.export_mef(user_id=user_id)
            nodes_raw = [x for x in (snapshot.get("nodes") or []) if str(x.get("session_id") or "") in {"", scoped_sid}]
            edges_raw = snapshot.get("edges") or []
            allowed_node_ids = {str(x.get("id") or "") for x in nodes_raw}
            edges = []
            for e in edges_raw:
                src = e.get("src_node_id") or e.get("source")
                dst = e.get("dst_node_id") or e.get("target")
                if src in allowed_node_ids and dst in allowed_node_ids:
                    edges.append(
                        {
                            "source": src,
                            "target": dst,
                            "type": e.get("edge_type") or e.get("type") or "",
                            "weight": e.get("weight", 1.0),
                        }
                    )
            nodes = [
                {
                    "id": n.get("id"),
                    "type": str(n.get("node_type") or n.get("type") or "").lower(),
                    "content": n.get("content", ""),
                    "layer": 1 if str(n.get("node_type") or "") == "token" else 0,
                    "importance": n.get("importance", 0.5),
                    "access_count": 0,
                    "created_at": n.get("created_at"),
                    "role": "",
                    "memory_type": "",
                    "memory_source": "sqlite_graph",
                }
                for n in nodes_raw
            ]
            return {
                "status": "success",
                "session_id": session_id,
                "graph_available": True,
                "graph_mode": "sqlite_graph",
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "layers": {
                        "hot": len([x for x in nodes if x.get("layer") == 0]),
                        "warm": len([x for x in nodes if x.get("layer") == 1]),
                        "cold": len([x for x in nodes if x.get("layer") == 2]),
                    },
                },
            }
        if adapter and str(getattr(adapter, "store_backend", "")).strip().lower() == "flat_memory":
            return {
                "status": "success",
                "session_id": session_id,
                "graph_available": False,
                "graph_mode": "none",
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }
        payload = await dispatch_gateway_method(
            RequestType.MEMORY_GRAPH,
            {"session_id": session_id},
            user_id=user_id,
        )
        return {"status": "success", "graph_available": True, "graph_mode": "neo4j", **payload}
    except HTTPException as e:
        # Fresh sessions may not have memory nodes yet. Keep UI stable with empty graph.
        if e.status_code == 404:
            return {
                "status": "success",
                "session_id": session_id,
                "graph_available": True,
                "graph_mode": "neo4j",
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }
        raise


@router.get("/memory/capabilities")
async def get_memory_capabilities(user_id: str = Depends(get_current_user_id)):
    _, memory_service = _get_runtime_components()
    adapter = _get_memory_adapter()
    caps = adapter.get_capabilities() if hasattr(adapter, "get_capabilities") else {}
    if not isinstance(caps, dict):
        caps = {}
    return {
        "status": "success",
        "user_id": user_id,
        "enabled": bool(memory_service.is_enabled()),
        "capabilities": {
            "backend": str(caps.get("backend") or getattr(adapter, "store_backend", "unknown")),
            "supports_graph": bool(caps.get("supports_graph", False)),
            "supports_crud": bool(caps.get("supports_crud", False)),
            "supports_recall_runs": bool(caps.get("supports_recall_runs", True)),
            "supports_write_inspector": bool(caps.get("supports_write_inspector", True)),
        },
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
    adapter = _get_memory_adapter()
    if not getattr(adapter, "is_enabled", lambda: False)():
        raise HTTPException(status_code=503, detail="Memory system not enabled")

    type_list = [x.strip().lower() for x in str(memory_types or "").split(",") if x.strip()]
    scope_norm = str(scope or "all").strip().lower()
    if scope_norm == "user" and not type_list:
        type_list = ["goal", "preference", "constraint", "identity"]
    elif scope_norm == "project" and not type_list:
        type_list = ["project_state"]
    rows = adapter.list_memory_entries(
        user_id=user_id,
        session_id=session_id,
        memory_types=type_list or None,
        query=q,
        limit=limit,
        offset=offset,
    )
    if not include_archived:
        rows = [x for x in rows if str(x.get("status") or "active") != "archived"]
    return {"status": "success", "user_id": user_id, "entries": rows, "total": len(rows)}


@router.post("/memory/entries")
async def create_memory_entry(
    request: MemoryEntryCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    adapter = _get_memory_adapter()
    if not getattr(adapter, "is_enabled", lambda: False)():
        raise HTTPException(status_code=503, detail="Memory system not enabled")
    content = str(request.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    sid = str(request.session_id or "manual").strip()
    ok = adapter.add_message(
        session_id=sid,
        role="user",
        content=content,
        user_id=user_id,
        metadata={
            "memory_type": str(request.memory_type or "preference").strip().lower(),
            "source_layer": str(request.source_layer or "direct").strip().lower(),
            "memory_source": "user.manual_entry",
        },
    )
    if not ok:
        raise HTTPException(status_code=500, detail="failed to create memory entry")
    return {"status": "success", "created": True}


@router.patch("/memory/entries/{memory_id}")
async def update_memory_entry(
    memory_id: str,
    request: MemoryEntryUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    adapter = _get_memory_adapter()
    res = adapter.update_memory_entry(
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
    adapter = _get_memory_adapter()
    res = adapter.delete_memory_entry(user_id=user_id, memory_id=memory_id)
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
    _, memory_service = _get_runtime_components()
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
    _, memory_service = _get_runtime_components()
    rows = memory_service.list_write_proposals(user_id=user_id, status=status, limit=limit)
    return {"status": "success", "user_id": user_id, "proposals": rows, "total": len(rows)}


@router.post("/memory/write-proposals/{proposal_id}/decision")
async def decide_memory_write_proposal(
    proposal_id: str,
    request: MemoryProposalDecisionRequest,
    user_id: str = Depends(get_current_user_id),
):
    _, memory_service = _get_runtime_components()
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
    _, memory_service = _get_runtime_components()
    decisions = memory_service.list_write_decisions(user_id=user_id, session_id=session_id, limit=limit)
    recalls = memory_service.list_recall_runs(user_id=user_id, session_id=session_id, limit=limit)
    write_total = len(decisions)
    write_allow = len([x for x in decisions if str(x.get("decision") or "") == "allow"])
    reason_dist: Dict[str, int] = {}
    for row in decisions:
        reason = str(row.get("reason") or "unknown")
        reason_dist[reason] = reason_dist.get(reason, 0) + 1
    recall_total = len(recalls)
    recall_candidates = sum(int((x.get("metrics") or {}).get("total_candidates", 0) or 0) for x in recalls)
    recall_selected = sum(int((x.get("metrics") or {}).get("selected", 0) or 0) for x in recalls)
    layer_dist: Dict[str, int] = {}
    for run in recalls:
        for rec in run.get("memory_records") or []:
            layer = str((rec or {}).get("source_layer") or "unknown")
            layer_dist[layer] = layer_dist.get(layer, 0) + 1
    return {
        "status": "success",
        "user_id": user_id,
        "session_id": session_id,
        "write": {
            "candidates": write_total,
            "allow_rate": (write_allow / write_total) if write_total else 0.0,
            "reasons": reason_dist,
        },
        "recall": {
            "runs": recall_total,
            "candidates": recall_candidates,
            "selected": recall_selected,
            "top_k_hit_rate": (recall_selected / recall_candidates) if recall_candidates else 0.0,
            "layer_contribution": layer_dist,
        },
    }


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
