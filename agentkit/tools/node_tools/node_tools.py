from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List


class NodeToolsService:
    """Lightweight persistent node graph store for generic agent workflows."""

    def __init__(self, workspace_root: str | None = None):
        self.name = "node_tools"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_path = self.workspace_root / "memory" / "node_store.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    async def upsert_node(
        self,
        node_id: str,
        kind: str = "generic",
        data: Dict[str, Any] | None = None,
        tags: List[str] | None = None,
    ) -> Dict[str, Any]:
        if not node_id:
            raise ValueError("node_id is required")
        state = self._load_state()
        now = time.time()
        nodes = state.setdefault("nodes", {})
        prev = nodes.get(node_id, {})
        nodes[node_id] = {
            "node_id": node_id,
            "kind": kind or "generic",
            "data": dict(data or {}),
            "tags": sorted(set(tags or [])),
            "created_at": prev.get("created_at", now),
            "updated_at": now,
        }
        self._save_state(state)
        return {"ok": True, "node": nodes[node_id]}

    async def get_node(self, node_id: str) -> Dict[str, Any]:
        if not node_id:
            raise ValueError("node_id is required")
        state = self._load_state()
        node = state.get("nodes", {}).get(node_id)
        if not node:
            return {"ok": False, "error": "node not found", "node_id": node_id}
        return {"ok": True, "node": node}

    async def list_nodes(
        self,
        kind: str = "",
        tag: str = "",
        limit: int = 100,
    ) -> Dict[str, Any]:
        state = self._load_state()
        rows = list((state.get("nodes", {}) or {}).values())
        if kind:
            rows = [n for n in rows if str(n.get("kind", "")) == str(kind)]
        if tag:
            rows = [n for n in rows if str(tag) in (n.get("tags") or [])]
        rows = sorted(rows, key=lambda x: float(x.get("updated_at", 0)), reverse=True)
        rows = rows[: max(1, int(limit))]
        return {"ok": True, "total": len(rows), "nodes": rows}

    async def delete_node(self, node_id: str) -> Dict[str, Any]:
        if not node_id:
            raise ValueError("node_id is required")
        state = self._load_state()
        removed = state.get("nodes", {}).pop(node_id, None) is not None
        if removed:
            edges = state.get("edges", [])
            state["edges"] = [
                e
                for e in edges
                if str(e.get("source")) != str(node_id)
                and str(e.get("target")) != str(node_id)
            ]
            self._save_state(state)
        return {"ok": True, "removed": removed, "node_id": node_id}

    async def link_nodes(
        self,
        source: str,
        target: str,
        relation: str = "related_to",
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        if not source or not target:
            raise ValueError("source and target are required")
        state = self._load_state()
        nodes = state.get("nodes", {})
        if source not in nodes or target not in nodes:
            raise ValueError("source/target node does not exist")

        edge = {
            "source": source,
            "target": target,
            "relation": relation or "related_to",
            "weight": float(weight),
            "updated_at": time.time(),
        }
        edges = state.setdefault("edges", [])
        replaced = False
        for i, e in enumerate(edges):
            if (
                str(e.get("source")) == source
                and str(e.get("target")) == target
                and str(e.get("relation")) == str(edge["relation"])
            ):
                edges[i] = edge
                replaced = True
                break
        if not replaced:
            edges.append(edge)
        self._save_state(state)
        return {"ok": True, "edge": edge, "replaced": replaced}

    async def list_links(self, node_id: str = "") -> Dict[str, Any]:
        state = self._load_state()
        edges = list(state.get("edges", []))
        if node_id:
            edges = [
                e
                for e in edges
                if str(e.get("source")) == str(node_id)
                or str(e.get("target")) == str(node_id)
            ]
        return {"ok": True, "total": len(edges), "edges": edges}

    def _load_state(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return {"nodes": {}, "edges": []}
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("nodes", {})
                raw.setdefault("edges", [])
                return raw
            return {"nodes": {}, "edges": []}
        except Exception:
            return {"nodes": {}, "edges": []}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
