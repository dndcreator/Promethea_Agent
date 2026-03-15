from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import MemoryStore
from memory.session_scope import scoped_session_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> List[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", _normalize(text))
    out: List[str] = []
    for c in chunks:
        if re.fullmatch(r"[a-z0-9_]+", c):
            out.extend([x for x in c.split("_") if x])
        else:
            out.append(c)
    return [x for x in out if len(x) >= 2]


class FlatMemoryStore(MemoryStore):
    """JSONL fallback backend (OpenClaw-like baseline memory)."""

    def __init__(self, file_path: str) -> None:
        self.file_path = str(file_path)
        Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.file_path).touch(exist_ok=True)
        self._lock = threading.RLock()

    def is_ready(self) -> bool:
        return True

    def _append_row(self, row: Dict[str, Any]) -> None:
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _load_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    rows.append(json.loads(text))
                except Exception:
                    continue
        return rows

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        txt = str(content or "").strip()
        if not txt:
            return False
        md = dict(metadata or {})
        row = {
            "id": f"flat:{uuid.uuid4().hex}",
            "user_id": user_id,
            "session_id": scoped_session_id(session_id, user_id),
            "role": role,
            "memory_type": str(md.get("memory_type") or ("episodic" if role == "user" else "working")),
            "source_layer": str(md.get("source_layer") or ("direct" if role == "user" else "recent")),
            "content": txt,
            "semantic_keys": md.get("semantic_keys") or _tokenize(txt)[:10],
            "importance": float(md.get("importance", 0.6 if role == "user" else 0.4)),
            "created_at": _utc_now_iso(),
            "metadata": md,
        }
        with self._lock:
            self._append_row(row)
        return True

    def collect_recall_candidates(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        top_k: int = 8,
        mode: str = "fast",
    ) -> List[Dict[str, Any]]:
        tokens = _tokenize(query)[:8]
        scoped_sid = scoped_session_id(session_id, user_id)
        with self._lock:
            rows = [r for r in self._load_rows() if str(r.get("user_id") or "") == str(user_id)]
        scored: List[Dict[str, Any]] = []
        for row in rows:
            content = str(row.get("content") or "")
            base = _normalize(content)
            hit = 0
            for tk in tokens:
                if tk in base:
                    hit += 1
            score = hit / max(1, len(tokens)) if tokens else 0.0
            if str(row.get("session_id") or "") == scoped_sid:
                score += 0.08
            if score <= 0 and len(scored) > 48:
                continue
            scored.append(
                {
                    "memory_id": row.get("id"),
                    "source_layer": row.get("source_layer") or "recent",
                    "content": content,
                    "importance": float(row.get("importance") or 0.5),
                    "created_at": row.get("created_at"),
                    "source_session": row.get("session_id"),
                    "owner_user_id": user_id,
                    "relevance_score": min(1.0, score),
                }
            )
        scored.sort(
            key=lambda x: (
                float(x.get("relevance_score") or 0.0),
                float(x.get("importance") or 0.0),
                str(x.get("created_at") or ""),
            ),
            reverse=True,
        )
        return scored[: max(3, int(top_k) * 2)]

    def get_context(self, *, query: str, session_id: str, user_id: str) -> str:
        rows = self.collect_recall_candidates(query=query, session_id=session_id, user_id=user_id, top_k=5, mode="fast")
        if not rows:
            return ""
        lines = []
        for row in rows[:5]:
            lines.append(f"- {str(row.get('content') or '').replace(chr(10), ' ')[:140]}")
        return "\n".join(lines)

    def export_mef(self, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            rows = self._load_rows()
        if user_id:
            rows = [x for x in rows if str(x.get("user_id") or "") == str(user_id)]
        return {
            "version": "1.0",
            "source_backend": "flat_memory",
            "exported_at": _utc_now_iso(),
            "memory_items": rows,
            "nodes": [],
            "edges": [],
            "metadata": {"file_path": self.file_path},
        }

    def import_mef(self, payload: Dict[str, Any], *, merge: bool = True) -> Dict[str, Any]:
        incoming = list(payload.get("memory_items") or [])
        with self._lock:
            rows = self._load_rows() if merge else []
            existing_ids = {str(r.get("id")) for r in rows}
            imported = 0
            for row in incoming:
                row_id = str(row.get("id") or "")
                if merge and row_id and row_id in existing_ids:
                    continue
                rows.append(row)
                if row_id:
                    existing_ids.add(row_id)
                imported += 1
            with open(self.file_path, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "imported": {"memory_items": imported, "nodes": 0, "edges": 0}, "merge": bool(merge)}

