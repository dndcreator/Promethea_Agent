from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import MemoryStore
from memory.session_scope import scoped_session_id, user_node_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_rel_type(value: Any) -> str:
    raw = str(value or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9_]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or "RELATED_TO"


def _load_json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return {}
    return {}


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


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
            return self._add_message_via_connector(
                session_id=session_id,
                role=role,
                content=content,
                user_id=user_id,
                metadata=metadata,
            )
        scoped_sid = scoped_session_id(session_id, user_id)
        self.adapter.hot_layer.session_id = scoped_sid
        self.adapter.hot_layer.user_id = user_id
        ctx = self.adapter._get_context(scoped_sid)
        self.adapter.hot_layer.process_message(role, content, ctx, metadata=metadata)
        self.adapter._update_cache(scoped_sid, role, content)
        return True

    def _add_message_via_connector(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
    ) -> bool:
        if not self.connector:
            return False
        txt = str(content or "").strip()
        if not txt:
            return False
        uid_raw = str(user_id or "default_user").strip() or "default_user"
        uid_node = user_node_id(uid_raw)
        scoped_sid = scoped_session_id(session_id, uid_raw)
        sid_node = f"session_{scoped_sid}"
        now = _utc_now_iso()
        md = dict(metadata or {})
        mid = str(message_id or md.get("id") or f"m:{uuid.uuid4().hex}")
        message_props: Dict[str, Any] = {
            "id": mid,
            "user_id": uid_raw,
            "session_id": scoped_sid,
            "role": str(role or "user").strip().lower() or "user",
            "content": txt,
            "memory_type": str(md.get("memory_type") or "episodic"),
            "target_memory_layer": str(md.get("source_layer") or "direct"),
            "importance": _to_float(md.get("importance", 0.6), 0.6),
            "created_at": str(md.get("created_at") or now),
            "updated_at": now,
            "metadata_json": json.dumps(md, ensure_ascii=False),
        }
        try:
            self.connector.query(
                """
                MERGE (u:User {id: $uid_node})
                ON CREATE SET u.user_id = $uid_raw, u.created_at = datetime($now)
                SET u.updated_at = datetime($now)
                MERGE (s:Session {id: $sid_node})
                ON CREATE SET s.created_at = datetime($now)
                SET s.session_id = $scoped_sid,
                    s.user_id = $uid_raw,
                    s.updated_at = datetime($now)
                MERGE (s)-[:OWNED_BY]->(u)
                MERGE (m:Message {id: $mid})
                SET m += $message_props
                MERGE (m)-[:PART_OF_SESSION]->(s)
                """,
                {
                    "uid_node": uid_node,
                    "uid_raw": uid_raw,
                    "sid_node": sid_node,
                    "scoped_sid": scoped_sid,
                    "mid": mid,
                    "message_props": message_props,
                    "now": now,
                },
            )
            return True
        except Exception:
            return False

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
        # Export user-scoped graph snapshot (messages + nodes + edges).
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
        uid_node = user_node_id(uid)
        uid_raw = uid_node[5:] if uid_node.startswith("user_") else uid_node
        rows = self.connector.query(
            """
            MATCH (u:User {id: $uid})<-[:OWNED_BY]-(s:Session)<-[:PART_OF_SESSION]-(m:Message)
            RETURN properties(m) AS props, s.id AS session_id
            ORDER BY m.created_at DESC
            LIMIT 5000
            """,
            {"uid": uid_node},
        )
        memory_items: List[Dict[str, Any]] = []
        for row in rows or []:
            props = dict(row.get("props") or {})
            sid = str(row.get("session_id") or props.get("session_id") or "")
            sid = sid[8:] if sid.startswith("session_") else sid
            metadata = _load_json_object(props.get("metadata_json"))
            if "metadata_json" not in metadata:
                metadata["metadata_json"] = props.get("metadata_json")
            memory_items.append(
                {
                    "id": props.get("id"),
                    "user_id": str(props.get("user_id") or uid_raw),
                    "session_id": sid,
                    "role": props.get("role") or "user",
                    "memory_type": props.get("memory_type") or "episodic",
                    "source_layer": props.get("target_memory_layer") or "direct",
                    "content": props.get("content") or "",
                    "semantic_keys_json": props.get("semantic_keys_json") or "[]",
                    "importance": _to_float(props.get("importance", 0.6), 0.6),
                    "created_at": props.get("created_at") or _utc_now_iso(),
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                }
            )
        node_rows = self.connector.query(
            """
            MATCH (u:User {id: $uid})
            OPTIONAL MATCH (u)<-[:OWNED_BY]-(s:Session)
            OPTIONAL MATCH (s)<-[:PART_OF_SESSION]-(m:Message)
            WITH collect(DISTINCT u) + collect(DISTINCT s) + collect(DISTINCT m) AS seed
            UNWIND seed AS n
            WITH DISTINCT n WHERE n IS NOT NULL
            OPTIONAL MATCH (n)-[]-(nbr)
            WITH collect(DISTINCT n) + collect(DISTINCT nbr) AS all_nodes
            UNWIND all_nodes AS x
            WITH DISTINCT x WHERE x IS NOT NULL
            RETURN elementId(x) AS element_id, labels(x) AS labels, properties(x) AS props
            LIMIT 20000
            """,
            {"uid": uid_node},
        )
        nodes: List[Dict[str, Any]] = []
        element_to_node_id: Dict[str, str] = {}
        for row in node_rows or []:
            props = dict(row.get("props") or {})
            labels = [str(x) for x in (row.get("labels") or [])]
            element_id = str(row.get("element_id") or "")
            node_id = str(props.get("id") or f"neo4j_node:{element_id.replace(':', '_')}")
            element_to_node_id[element_id] = node_id
            node_type = "entity"
            if "User" in labels:
                node_type = "user"
            elif "Session" in labels:
                node_type = "session"
            elif "Message" in labels:
                node_type = "message"
            session_id_val = str(props.get("session_id") or "")
            if not session_id_val and node_type == "session":
                session_id_val = node_id[8:] if node_id.startswith("session_") else node_id
            metadata = {"labels": labels, "original_properties": props}
            nodes.append(
                {
                    "id": node_id,
                    "user_id": str(props.get("user_id") or uid_raw),
                    "session_id": session_id_val,
                    "node_type": node_type,
                    "title": str(props.get("title") or props.get("name") or node_id),
                    "content": str(props.get("content") or ""),
                    "tags_json": props.get("tags_json") or "[]",
                    "importance": _to_float(props.get("importance", 0.5), 0.5),
                    "created_at": str(props.get("created_at") or _utc_now_iso()),
                    "updated_at": str(props.get("updated_at") or props.get("created_at") or _utc_now_iso()),
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                }
            )
        edge_rows: List[Dict[str, Any]] = []
        if element_to_node_id:
            edge_rows = self.connector.query(
                """
                MATCH (a)-[r]->(b)
                WHERE elementId(a) IN $node_ids AND elementId(b) IN $node_ids
                RETURN elementId(a) AS src_id,
                       elementId(b) AS dst_id,
                       type(r) AS rel_type,
                       properties(r) AS rel_props
                LIMIT 40000
                """,
                {"node_ids": list(element_to_node_id.keys())},
            )
        edges: List[Dict[str, Any]] = []
        for row in edge_rows or []:
            src_id = element_to_node_id.get(str(row.get("src_id") or ""))
            dst_id = element_to_node_id.get(str(row.get("dst_id") or ""))
            if not src_id or not dst_id:
                continue
            rel_props = dict(row.get("rel_props") or {})
            edges.append(
                {
                    "id": str(rel_props.get("id") or f"edge:{uuid.uuid4().hex}"),
                    "user_id": str(rel_props.get("user_id") or uid_raw),
                    "src_node_id": src_id,
                    "dst_node_id": dst_id,
                    "edge_type": str(row.get("rel_type") or "related").lower(),
                    "weight": _to_float(rel_props.get("weight", 0.5), 0.5),
                    "created_at": str(rel_props.get("created_at") or _utc_now_iso()),
                    "metadata_json": json.dumps({"original_properties": rel_props}, ensure_ascii=False),
                }
            )
        return {
            "version": "1.0",
            "source_backend": "neo4j",
            "exported_at": _utc_now_iso(),
            "memory_items": memory_items,
            "nodes": nodes,
            "edges": edges,
            "metadata": {"mode": "graph_snapshot"},
        }

    def import_mef(self, payload: Dict[str, Any], *, merge: bool = True) -> Dict[str, Any]:
        imported_items = 0
        skipped_items = 0
        imported_nodes = 0
        skipped_nodes = 0
        imported_edges = 0
        skipped_edges = 0
        errors: List[str] = []
        node_rows = (payload or {}).get("nodes") or []
        edge_rows = (payload or {}).get("edges") or []
        rows = (payload or {}).get("memory_items") or []
        if not isinstance(node_rows, list):
            node_rows = []
        if not isinstance(edge_rows, list):
            edge_rows = []
        if not isinstance(rows, list):
            rows = []

        if not merge:
            errors.append("merge=false is treated as append-only in neo4j adapter")

        if self.connector:
            for row in node_rows:
                if not isinstance(row, dict):
                    skipped_nodes += 1
                    continue
                node_id = str(row.get("id") or "").strip()
                if not node_id:
                    skipped_nodes += 1
                    continue
                user_id = str(row.get("user_id") or "default_user").strip() or "default_user"
                node_type = str(row.get("node_type") or "").strip().lower()
                label = "MemoryNode"
                if node_type == "user":
                    label = "User"
                elif node_type == "session":
                    label = "Session"
                elif node_type == "message":
                    label = "Message"
                metadata = _load_json_object(row.get("metadata_json"))
                props = {}
                original_props = metadata.get("original_properties")
                if isinstance(original_props, dict):
                    props.update(original_props)
                props.update(
                    {
                        "id": node_id,
                        "user_id": user_id,
                        "session_id": row.get("session_id"),
                        "node_type": node_type or props.get("node_type") or label.lower(),
                        "title": row.get("title"),
                        "content": row.get("content"),
                        "importance": _to_float(row.get("importance", props.get("importance", 0.5)), 0.5),
                        "created_at": str(row.get("created_at") or props.get("created_at") or _utc_now_iso()),
                        "updated_at": str(row.get("updated_at") or _utc_now_iso()),
                    }
                )
                try:
                    self.connector.query(
                        f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                        {"id": node_id, "props": props},
                    )
                    imported_nodes += 1
                except Exception as exc:
                    skipped_nodes += 1
                    errors.append(str(exc))

            for row in edge_rows:
                if not isinstance(row, dict):
                    skipped_edges += 1
                    continue
                src_id = str(row.get("src_node_id") or "").strip()
                dst_id = str(row.get("dst_node_id") or "").strip()
                if not src_id or not dst_id:
                    skipped_edges += 1
                    continue
                rel_id = str(row.get("id") or f"edge:{uuid.uuid4().hex}")
                rel_type = _safe_rel_type(row.get("edge_type"))
                metadata = _load_json_object(row.get("metadata_json"))
                props = {}
                original_props = metadata.get("original_properties")
                if isinstance(original_props, dict):
                    props.update(original_props)
                props.update(
                    {
                        "id": rel_id,
                        "user_id": str(row.get("user_id") or "default_user"),
                        "weight": _to_float(row.get("weight", props.get("weight", 0.5)), 0.5),
                        "created_at": str(row.get("created_at") or props.get("created_at") or _utc_now_iso()),
                        "updated_at": _utc_now_iso(),
                    }
                )
                try:
                    self.connector.query(
                        f"""
                        MATCH (a {{id: $src_id}}), (b {{id: $dst_id}})
                        MERGE (a)-[r:{rel_type} {{id: $rel_id}}]->(b)
                        SET r += $props
                        """,
                        {"src_id": src_id, "dst_id": dst_id, "rel_id": rel_id, "props": props},
                    )
                    imported_edges += 1
                except Exception as exc:
                    skipped_edges += 1
                    errors.append(str(exc))

        for row in rows:
            if not isinstance(row, dict):
                skipped_items += 1
                continue
            user_id = str(row.get("user_id") or "default_user").strip() or "default_user"
            session_id = str(row.get("session_id") or "default_session").strip() or "default_session"
            role = str(row.get("role") or "user").strip().lower() or "user"
            content = str(row.get("content") or "")
            if not content:
                skipped_items += 1
                continue
            try:
                metadata = {
                    "import_source": "mef",
                    "memory_type": row.get("memory_type"),
                    "source_layer": row.get("source_layer"),
                    "created_at": row.get("created_at"),
                }
                metadata.update(_load_json_object(row.get("metadata_json")))
                mid = str(row.get("id") or f"m:{uuid.uuid4().hex}")
                if self.connector:
                    ok = self._add_message_via_connector(
                        session_id=session_id,
                        role=role,
                        content=content,
                        user_id=user_id,
                        metadata=metadata,
                        message_id=mid,
                    )
                else:
                    ok = self.add_message(
                        session_id=session_id,
                        role=role,
                        content=content,
                        user_id=user_id,
                        metadata=metadata,
                    )
                if ok:
                    imported_items += 1
                else:
                    skipped_items += 1
            except Exception as exc:
                skipped_items += 1
                errors.append(str(exc))

        return {
            "ok": (imported_items + imported_nodes + imported_edges) > 0 and not errors,
            "imported": {"memory_items": imported_items, "nodes": imported_nodes, "edges": imported_edges},
            "skipped": {"memory_items": skipped_items, "nodes": skipped_nodes, "edges": skipped_edges},
            "merge": bool(merge),
            "errors": errors[:20],
            "reason": None if (imported_items + imported_nodes + imported_edges) > 0 else "no_importable_memory_items",
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
