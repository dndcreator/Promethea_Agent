from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import MemoryStore
from memory.session_scope import scoped_session_id, user_node_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Neo4jMemoryStore(MemoryStore):
    """
    Thin adapter over existing Neo4j-based memory stack.

    This keeps current behavior while exposing the unified store contract.
    """

    def __init__(self, *, adapter: Any, connector: Any = None, recall_engine: Any = None) -> None:
        self.adapter = adapter
        self.connector = connector
        self.recall_engine = recall_engine

    def is_ready(self) -> bool:
        return self.connector is not None

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        # Delegate to existing hot-layer flow to preserve current behavior.
        if not self.adapter or not getattr(self.adapter, "hot_layer", None):
            return False
        scoped_sid = scoped_session_id(session_id, user_id)
        self.adapter.hot_layer.session_id = scoped_sid
        self.adapter.hot_layer.user_id = user_id
        ctx = self.adapter._get_context(scoped_sid)
        self.adapter.hot_layer.process_message(role, content, ctx, metadata=metadata)
        self.adapter._update_cache(scoped_sid, role, content)
        return True

    def get_context(self, *, query: str, session_id: str, user_id: str) -> str:
        if not self.recall_engine:
            return ""
        return self.recall_engine.recall(query, scoped_session_id(session_id, user_id), user_id)

    def collect_recall_candidates(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        top_k: int = 8,
        mode: str = "fast",
    ) -> List[Dict[str, Any]]:
        if not self.connector:
            return []
        rows: List[Dict[str, Any]] = []
        try:
            q = str(query or "").strip().lower()
            if not q:
                return []
            result = self.connector.query(
                """
                MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)<-[:PART_OF_SESSION]-(m:Message)
                WHERE toLower(m.content) CONTAINS $query
                RETURN m.id AS memory_id,
                       m.content AS content,
                       m.created_at AS created_at,
                       s.id AS source_session
                ORDER BY m.created_at DESC
                LIMIT $limit
                """,
                {
                    "user_node_id": user_node_id(user_id),
                    "query": q,
                    "limit": int(max(4, top_k * 3)),
                },
            )
            for row in result or []:
                rows.append(
                    {
                        "memory_id": str(row.get("memory_id") or ""),
                        "source_layer": "direct",
                        "content": str(row.get("content") or ""),
                        "importance": 0.6,
                        "created_at": row.get("created_at") or _utc_now_iso(),
                        "source_session": row.get("source_session"),
                        "owner_user_id": user_id,
                        "relevance_score": 0.72,
                    }
                )
        except Exception:
            return []
        return rows

    def export_mef(self, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        # Best-effort export focused on message memory surface.
        if not self.connector:
            return {
                "version": "1.0",
                "source_backend": "neo4j",
                "exported_at": _utc_now_iso(),
                "memory_items": [],
                "nodes": [],
                "edges": [],
                "metadata": {"note": "connector_unavailable"},
            }
        uid = str(user_id or "default_user")
        rows = self.connector.query(
            """
            MATCH (u:User {id: $uid})<-[:OWNED_BY]-(s:Session)<-[:PART_OF_SESSION]-(m:Message)
            RETURN m.id AS id, s.id AS session_id, m.role AS role, m.content AS content, m.created_at AS created_at
            ORDER BY m.created_at DESC
            LIMIT 5000
            """,
            {"uid": user_node_id(uid)},
        )
        memory_items: List[Dict[str, Any]] = []
        for row in rows or []:
            memory_items.append(
                {
                    "id": row.get("id"),
                    "user_id": uid,
                    "session_id": row.get("session_id"),
                    "role": row.get("role") or "user",
                    "memory_type": "episodic",
                    "source_layer": "direct",
                    "content": row.get("content") or "",
                    "semantic_keys_json": "[]",
                    "importance": 0.6,
                    "created_at": row.get("created_at") or _utc_now_iso(),
                    "metadata_json": "{}",
                }
            )
        return {
            "version": "1.0",
            "source_backend": "neo4j",
            "exported_at": _utc_now_iso(),
            "memory_items": memory_items,
            "nodes": [],
            "edges": [],
            "metadata": {"mode": "messages_only"},
        }

    def import_mef(self, payload: Dict[str, Any], *, merge: bool = True) -> Dict[str, Any]:
        # Kept conservative: no direct graph writes for now.
        return {
            "ok": False,
            "imported": {"memory_items": 0, "nodes": 0, "edges": 0},
            "merge": bool(merge),
            "reason": "neo4j direct import not implemented in unified adapter yet",
        }

    def list_memory_entries(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        memory_types: Optional[List[str]] = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self.connector:
            return []
        scoped_sid = scoped_session_id(session_id, user_id) if session_id else None
        where = [
            "EXISTS { MATCH (m)-[:PART_OF_SESSION]->(:Session)-[:OWNED_BY]->(:User {id: $uid}) }",
        ]
        params: Dict[str, Any] = {
            "uid": user_node_id(user_id),
            "limit": max(1, min(500, int(limit))),
            "offset": max(0, int(offset)),
        }
        if scoped_sid:
            where.append("EXISTS { MATCH (m)-[:PART_OF_SESSION]->(:Session {id: $session_id}) }")
            params["session_id"] = f"session_{scoped_sid}"
        wanted_types = [str(x).strip().lower() for x in (memory_types or []) if str(x).strip()]
        if wanted_types:
            where.append("toLower(coalesce(m.memory_type,'')) IN $memory_types")
            params["memory_types"] = wanted_types
        q = str(query or "").strip().lower()
        if q:
            where.append("toLower(m.content) CONTAINS $query")
            params["query"] = q
        cypher = f"""
            MATCH (m:Message)
            WHERE {" AND ".join(where)}
            OPTIONAL MATCH (m)-[:PART_OF_SESSION]->(s:Session)
            RETURN m.id AS memory_id,
                   m.user_id AS user_id,
                   s.id AS session_id,
                   m.role AS role,
                   coalesce(m.memory_type, 'episodic') AS memory_type,
                   coalesce(m.target_memory_layer, 'direct') AS source_layer,
                   m.content AS content,
                   coalesce(m.importance, 0.6) AS importance,
                   m.created_at AS created_at,
                   coalesce(m.updated_at, m.created_at) AS updated_at,
                   coalesce(m.status, 'active') AS status
            ORDER BY m.created_at DESC
            SKIP $offset LIMIT $limit
        """
        rows = self.connector.query(cypher, params)
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            raw_sid = str(row.get("session_id") or "")
            sid = raw_sid[8:] if raw_sid.startswith("session_") else raw_sid
            out.append(
                {
                    "memory_id": str(row.get("memory_id") or ""),
                    "user_id": user_id,
                    "session_id": sid,
                    "role": str(row.get("role") or "user"),
                    "memory_type": str(row.get("memory_type") or "episodic"),
                    "source_layer": str(row.get("source_layer") or "direct"),
                    "content": str(row.get("content") or ""),
                    "importance": float(row.get("importance") or 0.5),
                    "created_at": row.get("created_at") or _utc_now_iso(),
                    "updated_at": row.get("updated_at") or row.get("created_at") or _utc_now_iso(),
                    "status": str(row.get("status") or "active"),
                    "metadata": {},
                }
            )
        return out

    def update_memory_entry(
        self,
        *,
        user_id: str,
        memory_id: str,
        content: Optional[str] = None,
        memory_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.connector:
            return {"ok": False, "reason": "connector_unavailable"}
        mid = str(memory_id or "").strip()
        if not mid:
            return {"ok": False, "reason": "memory_id_required"}
        sets: List[str] = ["m.updated_at = datetime($updated_at)"]
        params: Dict[str, Any] = {
            "memory_id": mid,
            "uid": user_node_id(user_id),
            "updated_at": _utc_now_iso(),
        }
        if content is not None:
            sets.append("m.content = $content")
            params["content"] = str(content)
        if memory_type is not None:
            sets.append("m.memory_type = $memory_type")
            params["memory_type"] = str(memory_type).strip().lower()
        if metadata:
            for k, v in metadata.items():
                if not str(k).strip():
                    continue
                key = f"meta_{k}"
                sets.append(f"m.{str(k).strip()} = ${key}")
                params[key] = v
        if len(sets) == 1:
            return {"ok": False, "reason": "no_change"}
        cypher = f"""
            MATCH (m:Message {{id: $memory_id}})
            WHERE EXISTS {{ MATCH (m)-[:PART_OF_SESSION]->(:Session)-[:OWNED_BY]->(:User {{id: $uid}}) }}
            SET {", ".join(sets)}
            RETURN m.id AS memory_id
        """
        rows = self.connector.query(cypher, params)
        return {"ok": bool(rows), "reason": None if rows else "not_found"}

    def delete_memory_entry(
        self,
        *,
        user_id: str,
        memory_id: str,
    ) -> Dict[str, Any]:
        if not self.connector:
            return {"ok": False, "reason": "connector_unavailable"}
        mid = str(memory_id or "").strip()
        if not mid:
            return {"ok": False, "reason": "memory_id_required"}
        rows = self.connector.query(
            """
            MATCH (m:Message {id: $memory_id})
            WHERE EXISTS { MATCH (m)-[:PART_OF_SESSION]->(:Session)-[:OWNED_BY]->(:User {id: $uid}) }
            SET m.status = 'archived', m.updated_at = datetime($updated_at)
            RETURN m.id AS memory_id
            """,
            {
                "memory_id": mid,
                "uid": user_node_id(user_id),
                "updated_at": _utc_now_iso(),
            },
        )
        return {"ok": bool(rows), "reason": None if rows else "not_found"}

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "backend": "neo4j",
            "supports_graph": True,
            "supports_crud": True,
            "supports_recall_runs": True,
            "supports_write_inspector": True,
        }
