from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import MemoryStore
from memory.session_scope import scoped_session_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> List[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", _normalize_text(text))
    out: List[str] = []
    for c in chunks:
        if re.fullmatch(r"[a-z0-9_]+", c):
            out.extend([p for p in c.split("_") if p])
        else:
            out.append(c)
    return [x for x in out if len(x) >= 2]


def _score_overlap(tokens: List[str], text: str) -> float:
    if not tokens:
        return 0.0
    hay = _normalize_text(text)
    hit = 0
    for t in tokens:
        if t in hay:
            hit += 1
    return hit / max(1, len(tokens))


class SqliteGraphMemoryStore(MemoryStore):
    """
    Lightweight graph-capable memory backend using sqlite3.

    Graph ability:
    - nodes/edges model
    - memory_items linked to nodes
    - recursive CTE traversal for related-memory recall
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    node_type TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    tags_json TEXT,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    src_node_id TEXT NOT NULL,
                    dst_node_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    weight REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    source_layer TEXT NOT NULL,
                    content TEXT NOT NULL,
                    semantic_keys_json TEXT,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    source_turn INTEGER,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                    memory_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    PRIMARY KEY(memory_id, node_id)
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_user_type ON nodes(user_id, node_type);
                CREATE INDEX IF NOT EXISTS idx_edges_user_src ON edges(user_id, src_node_id);
                CREATE INDEX IF NOT EXISTS idx_edges_user_dst ON edges(user_id, dst_node_id);
                CREATE INDEX IF NOT EXISTS idx_mem_user_time ON memory_items(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mem_user_session_time ON memory_items(user_id, session_id, created_at DESC);
                """
            )

    def is_ready(self) -> bool:
        return self._conn is not None

    def _upsert_token_nodes_and_edges(
        self,
        *,
        user_id: str,
        session_id: str,
        memory_id: str,
        tokens: List[str],
    ) -> None:
        now = _utc_now_iso()
        unique_tokens = list(dict.fromkeys(tokens[:24]))
        for token in unique_tokens:
            node_id = f"tok:{user_id}:{token}"
            self._conn.execute(
                """
                INSERT INTO nodes(id, user_id, session_id, node_type, title, content, tags_json, importance, created_at, updated_at, metadata_json)
                VALUES(?, ?, ?, 'token', ?, ?, '[]', 0.5, ?, ?, '{}')
                ON CONFLICT(id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    content = excluded.content
                """,
                (node_id, user_id, session_id, token, token, now, now),
            )
            self._conn.execute(
                """
                INSERT INTO memory_links(memory_id, node_id, weight)
                VALUES(?, ?, 1.0)
                ON CONFLICT(memory_id, node_id) DO UPDATE SET weight=excluded.weight
                """,
                (memory_id, node_id),
            )

        # Build simple co-occurrence graph among tokens in the same memory item.
        for i, src in enumerate(unique_tokens):
            for dst in unique_tokens[i + 1 :]:
                src_id = f"tok:{user_id}:{src}"
                dst_id = f"tok:{user_id}:{dst}"
                eid_a = f"edge:{src_id}->{dst_id}"
                eid_b = f"edge:{dst_id}->{src_id}"
                for eid, a, b in ((eid_a, src_id, dst_id), (eid_b, dst_id, src_id)):
                    self._conn.execute(
                        """
                        INSERT INTO edges(id, user_id, src_node_id, dst_node_id, edge_type, weight, created_at, metadata_json)
                        VALUES(?, ?, ?, ?, 'cooccurs', 0.82, ?, '{}')
                        ON CONFLICT(id) DO UPDATE SET
                            weight = CASE WHEN edges.weight < 0.95 THEN edges.weight + 0.01 ELSE edges.weight END
                        """,
                        (eid, user_id, a, b, now),
                    )

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        scoped_sid = scoped_session_id(session_id, user_id)
        now = _utc_now_iso()
        memory_id = f"m:{uuid.uuid4().hex}"
        md = dict(metadata or {})
        memory_type = str(md.get("memory_type") or ("episodic" if role == "user" else "working"))
        source_layer = str(md.get("source_layer") or ("direct" if role == "user" else "recent"))
        semantic_keys = md.get("semantic_keys") if isinstance(md.get("semantic_keys"), list) else None
        if not semantic_keys:
            semantic_keys = _tokenize(text)[:10]

        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    INSERT INTO memory_items(
                        id, user_id, session_id, role, memory_type, source_layer, content,
                        semantic_keys_json, importance, created_at, last_used_at, source_turn, metadata_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        user_id,
                        scoped_sid,
                        role,
                        memory_type,
                        source_layer,
                        text,
                        json.dumps(semantic_keys, ensure_ascii=False),
                        float(md.get("importance", 0.65 if role == "user" else 0.45)),
                        now,
                        now,
                        int(md.get("source_turn", 0) or 0),
                        json.dumps(md, ensure_ascii=False),
                    ),
                )
                self._upsert_token_nodes_and_edges(
                    user_id=user_id,
                    session_id=scoped_sid,
                    memory_id=memory_id,
                    tokens=semantic_keys,
                )
            return True
        except Exception:
            return False

    def _recent_candidates(self, *, user_id: str, session_id: str, limit: int = 8) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, source_layer, content, importance, created_at, session_id
            FROM memory_items
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "memory_id": r["id"],
                    "source_layer": "recent",
                    "content": r["content"],
                    "importance": float(r["importance"] or 0.5),
                    "created_at": r["created_at"],
                    "source_session": r["session_id"],
                    "owner_user_id": user_id,
                    "relevance_score": 0.35,
                }
            )
        return out

    def collect_recall_candidates(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        top_k: int = 8,
        mode: str = "fast",
    ) -> List[Dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        scoped_sid = scoped_session_id(session_id, user_id)
        tokens = list(dict.fromkeys(_tokenize(q)))[:6]
        if not tokens:
            tokens = [q[:16].lower()]

        with self._lock:
            # Step-1 lexical seed memories.
            where_like = " OR ".join(["lower(content) LIKE ?"] * len(tokens))
            params: List[Any] = [user_id]
            params.extend([f"%{t.lower()}%" for t in tokens])
            seed_rows = self._conn.execute(
                f"""
                SELECT id, source_layer, content, importance, created_at, session_id
                FROM memory_items
                WHERE user_id = ? AND ({where_like})
                ORDER BY created_at DESC
                LIMIT 64
                """,
                params,
            ).fetchall()

            seed: Dict[str, Dict[str, Any]] = {}
            for r in seed_rows:
                score = _score_overlap(tokens, r["content"])
                if score <= 0:
                    continue
                seed[r["id"]] = {
                    "memory_id": r["id"],
                    "source_layer": r["source_layer"] or "direct",
                    "content": r["content"],
                    "importance": float(r["importance"] or 0.5),
                    "created_at": r["created_at"],
                    "source_session": r["session_id"],
                    "owner_user_id": user_id,
                    "relevance_score": min(1.0, score * 0.75 + float(r["importance"] or 0.5) * 0.25),
                }

            if not seed:
                return self._recent_candidates(user_id=user_id, session_id=scoped_sid, limit=top_k)

            # Step-2 recursive graph expansion from seed-linked nodes.
            seed_ids = list(seed.keys())[:12]
            qmarks = ",".join(["?"] * len(seed_ids))
            seed_nodes = self._conn.execute(
                f"""
                SELECT ml.node_id
                FROM memory_links ml
                WHERE ml.memory_id IN ({qmarks})
                """,
                seed_ids,
            ).fetchall()
            node_ids = [x["node_id"] for x in seed_nodes]

            graph_candidates: Dict[str, float] = {}
            if node_ids:
                values_sql = " UNION ALL ".join(["SELECT ? AS node_id, ? AS seed_score"] * len(node_ids))
                cte_params: List[Any] = []
                for nid in node_ids:
                    cte_params.extend([nid, 1.0])
                cte_params.extend([user_id, 2, user_id])
                cte_sql = f"""
                    WITH RECURSIVE seed_nodes(node_id, seed_score) AS (
                        {values_sql}
                    ),
                    walk(node_id, depth, score, path) AS (
                        SELECT node_id, 0, seed_score, node_id FROM seed_nodes
                        UNION ALL
                        SELECT e.dst_node_id,
                               w.depth + 1,
                               w.score * e.weight * 0.78,
                               w.path || ',' || e.dst_node_id
                        FROM walk w
                        JOIN edges e
                          ON e.src_node_id = w.node_id
                         AND e.user_id = ?
                        WHERE w.depth < ?
                          AND instr(w.path, e.dst_node_id) = 0
                    )
                    SELECT ml.memory_id, MAX(w.score * ml.weight) AS graph_score
                    FROM walk w
                    JOIN memory_links ml ON ml.node_id = w.node_id
                    JOIN memory_items mi ON mi.id = ml.memory_id AND mi.user_id = ?
                    GROUP BY ml.memory_id
                    ORDER BY graph_score DESC
                    LIMIT 96
                """
                rows = self._conn.execute(cte_sql, cte_params).fetchall()
                for r in rows:
                    graph_candidates[str(r["memory_id"])] = float(r["graph_score"] or 0.0)

            # Step-3 assemble candidates with related layer.
            all_ids = list(dict.fromkeys(list(seed.keys()) + list(graph_candidates.keys())))
            if not all_ids:
                return self._recent_candidates(user_id=user_id, session_id=scoped_sid, limit=top_k)
            ids_qmarks = ",".join(["?"] * len(all_ids))
            rows = self._conn.execute(
                f"""
                SELECT id, source_layer, content, importance, created_at, session_id
                FROM memory_items
                WHERE user_id = ? AND id IN ({ids_qmarks})
                """,
                [user_id, *all_ids],
            ).fetchall()

            assembled: List[Dict[str, Any]] = []
            for r in rows:
                mid = str(r["id"])
                seed_row = seed.get(mid)
                if seed_row:
                    assembled.append(seed_row)
                    continue
                gscore = graph_candidates.get(mid, 0.0)
                if gscore <= 0.08:
                    continue
                assembled.append(
                    {
                        "memory_id": mid,
                        "source_layer": "related",
                        "content": r["content"],
                        "importance": float(r["importance"] or 0.5),
                        "created_at": r["created_at"],
                        "source_session": r["session_id"],
                        "owner_user_id": user_id,
                        "relevance_score": min(1.0, gscore),
                    }
                )

            assembled.extend(self._recent_candidates(user_id=user_id, session_id=scoped_sid, limit=max(2, top_k // 2)))
            dedup: Dict[str, Dict[str, Any]] = {}
            for row in assembled:
                dedup[row["memory_id"]] = row
            ranked = sorted(
                dedup.values(),
                key=lambda x: (float(x.get("relevance_score") or 0.0), float(x.get("importance") or 0.0), str(x.get("created_at") or "")),
                reverse=True,
            )
            return ranked[: max(1, int(top_k) * 2)]

    def get_context(self, *, query: str, session_id: str, user_id: str) -> str:
        rows = self.collect_recall_candidates(query=query, session_id=session_id, user_id=user_id, top_k=5, mode="fast")
        if not rows:
            return ""
        lines = []
        current_layer = ""
        for row in rows[:5]:
            layer = str(row.get("source_layer") or "direct")
            if layer != current_layer:
                current_layer = layer
                lines.append(f"[{layer}]")
            txt = str(row.get("content") or "").replace("\n", " ").strip()
            lines.append(f"- {txt[:140]}")
        return "\n".join(lines)

    def export_mef(self, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            args: List[Any] = []
            where = ""
            if user_id:
                where = "WHERE user_id = ?"
                args.append(user_id)
            mem_rows = [dict(x) for x in self._conn.execute(f"SELECT * FROM memory_items {where}", args).fetchall()]
            node_rows = [dict(x) for x in self._conn.execute(f"SELECT * FROM nodes {where}", args).fetchall()]
            edge_rows = [dict(x) for x in self._conn.execute(f"SELECT * FROM edges {where}", args).fetchall()]
            return {
                "version": "1.0",
                "source_backend": "sqlite_graph",
                "exported_at": _utc_now_iso(),
                "memory_items": mem_rows,
                "nodes": node_rows,
                "edges": edge_rows,
                "metadata": {"db_path": self.db_path},
            }

    def import_mef(self, payload: Dict[str, Any], *, merge: bool = True) -> Dict[str, Any]:
        memory_items = list(payload.get("memory_items") or [])
        nodes = list(payload.get("nodes") or [])
        edges = list(payload.get("edges") or [])
        imported = {"memory_items": 0, "nodes": 0, "edges": 0}
        with self._lock, self._conn:
            if not merge:
                self._conn.execute("DELETE FROM memory_links")
                self._conn.execute("DELETE FROM edges")
                self._conn.execute("DELETE FROM nodes")
                self._conn.execute("DELETE FROM memory_items")
            for row in nodes:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO nodes(
                        id, user_id, session_id, node_type, title, content, tags_json,
                        importance, created_at, updated_at, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id"),
                        row.get("user_id"),
                        row.get("session_id"),
                        row.get("node_type") or "entity",
                        row.get("title"),
                        row.get("content"),
                        row.get("tags_json") or "[]",
                        float(row.get("importance") or 0.5),
                        row.get("created_at") or _utc_now_iso(),
                        row.get("updated_at") or _utc_now_iso(),
                        row.get("metadata_json") or "{}",
                    ),
                )
                imported["nodes"] += 1
            for row in edges:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO edges(
                        id, user_id, src_node_id, dst_node_id, edge_type, weight, created_at, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id") or f"edge:{uuid.uuid4().hex}",
                        row.get("user_id"),
                        row.get("src_node_id"),
                        row.get("dst_node_id"),
                        row.get("edge_type") or "related",
                        float(row.get("weight") or 0.5),
                        row.get("created_at") or _utc_now_iso(),
                        row.get("metadata_json") or "{}",
                    ),
                )
                imported["edges"] += 1
            for row in memory_items:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_items(
                        id, user_id, session_id, role, memory_type, source_layer, content, semantic_keys_json,
                        importance, created_at, last_used_at, source_turn, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id") or f"m:{uuid.uuid4().hex}",
                        row.get("user_id"),
                        row.get("session_id"),
                        row.get("role") or "user",
                        row.get("memory_type") or "episodic",
                        row.get("source_layer") or "direct",
                        row.get("content") or "",
                        row.get("semantic_keys_json") or "[]",
                        float(row.get("importance") or 0.5),
                        row.get("created_at") or _utc_now_iso(),
                        row.get("last_used_at") or _utc_now_iso(),
                        int(row.get("source_turn") or 0),
                        row.get("metadata_json") or "{}",
                    ),
                )
                imported["memory_items"] += 1
        return {"ok": True, "imported": imported, "merge": bool(merge)}
