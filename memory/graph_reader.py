"""Read backend graph views without invoking Memory write or recall policy."""

from __future__ import annotations

from typing import Any, Dict

from .session_scope import scoped_session_id, user_node_id


def read_user_graph(adapter: Any, *, user_id: str) -> Dict[str, Any]:
    backend = str(getattr(adapter, "store_backend", "")).strip().lower()
    try:
        if backend == "sqlite_graph":
            snapshot = adapter.export_mef(user_id=user_id)
            nodes_raw = snapshot.get("nodes") or []
            edges_raw = snapshot.get("edges") or []
            nodes = []
            for n in nodes_raw:
                node_type = str(n.get("node_type") or n.get("type") or "").lower()
                nodes.append(
                    {
                        "id": n.get("id"),
                        "type": node_type,
                        "content": n.get("content", ""),
                        "layer": 1 if node_type == "token" else 0,
                        "importance": n.get("importance", 0.5),
                        "access_count": 0,
                        "created_at": n.get("created_at"),
                        "role": "",
                        "memory_type": "",
                        "memory_source": "sqlite_graph",
                        "semantic_level": "lightweight",
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
                "ok": True,
                "status": "success",
                "user_id": user_id,
                "graph_available": True,
                "graph_mode": "sqlite_graph",
                "graph_semantics": "lightweight",
                "semantic_graph_available": False,
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
        if backend == "flat_memory":
            return {
                "ok": True,
                "status": "success",
                "user_id": user_id,
                "graph_available": False,
                "graph_mode": "none",
                "graph_semantics": "none",
                "semantic_graph_available": False,
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }

        if not getattr(adapter, "hot_layer", None):
            return {"ok": False, "reason": "hot_layer_unavailable"}
        connector = adapter.hot_layer.connector
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
        RETURN node.id AS id, head([label IN labels(node) WHERE NOT label STARTS WITH 'MemoryVector_']) AS type, node.content AS content,
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
                "semantic_level": "semantic",
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
            "ok": True,
            "status": "success",
            "user_id": user_id,
            "graph_available": True,
            "graph_mode": "neo4j",
            "graph_semantics": "semantic",
            "semantic_graph_available": True,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "layers": layer_counts,
            },
        }
    except Exception as e:
        return {"ok": False, "reason": f"graph_global_failed:{e}"}


def read_session_graph(adapter: Any, *, session_id: str, user_id: str) -> Dict[str, Any]:
    backend = str(getattr(adapter, "store_backend", "")).strip().lower()
    try:
        if backend == "sqlite_graph":
            scoped_sid = scoped_session_id(session_id, user_id)
            snapshot = adapter.export_mef(user_id=user_id)
            nodes_raw = [
                x
                for x in (snapshot.get("nodes") or [])
                if str(x.get("session_id") or "") in {"", scoped_sid}
            ]
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
            nodes = []
            for n in nodes_raw:
                node_type = str(n.get("node_type") or n.get("type") or "").lower()
                nodes.append(
                    {
                        "id": n.get("id"),
                        "type": node_type,
                        "content": n.get("content", ""),
                        "layer": 1 if node_type == "token" else 0,
                        "importance": n.get("importance", 0.5),
                        "access_count": 0,
                        "created_at": n.get("created_at"),
                        "role": "",
                        "memory_type": "",
                        "memory_source": "sqlite_graph",
                        "semantic_level": "lightweight",
                    }
                )
            return {
                "ok": True,
                "handled": True,
                "status": "success",
                "session_id": session_id,
                "graph_available": True,
                "graph_mode": "sqlite_graph",
                "graph_semantics": "lightweight",
                "semantic_graph_available": False,
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
        if backend == "flat_memory":
            return {
                "ok": True,
                "handled": True,
                "status": "success",
                "session_id": session_id,
                "graph_available": False,
                "graph_mode": "none",
                "graph_semantics": "none",
                "semantic_graph_available": False,
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }
        return {"ok": True, "handled": False}
    except Exception as e:
        return {"ok": False, "reason": f"graph_session_failed:{e}", "handled": False}
