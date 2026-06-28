from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .reasoning_utils import safe_user_segment


class ReasoningTreeHistoryStore:
    """Persistence boundary for completed reasoning traces."""

    def __init__(self, base_dir: Path | str = Path("brain") / "basal_ganglia" / "reasoning_traces") -> None:
        self.base_dir = Path(base_dir)

    def remember(self, payload: Dict[str, Any], cache: Dict[str, Dict[str, Any]], *, max_cache: int = 256) -> None:
        tree_id = str(payload.get("tree_id", "") or "")
        if not tree_id:
            return
        cache[tree_id] = dict(payload)
        self.persist(payload)
        if len(cache) > max_cache:
            oldest = next(iter(cache.keys()))
            cache.pop(oldest, None)

    def path_for_user(self, user_id: Optional[str]) -> Path:
        user_segment = safe_user_segment(user_id or "default_user")
        return self.base_dir / f"{user_segment}.jsonl"

    def persist(self, payload: Dict[str, Any]) -> None:
        try:
            path = self.path_for_user(str(payload.get("user_id") or "default_user"))
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": time.time(),
                "tree_id": str(payload.get("tree_id", "") or ""),
                "session_id": str(payload.get("session_id", "") or ""),
                "user_id": str(payload.get("user_id", "") or ""),
                "tree": payload,
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("ReasoningTreeHistoryStore: persist completed tree failed: {}", e)

    def load(self, *, tree_id: str, user_id: Optional[str]) -> Dict[str, Any]:
        try:
            path = self.path_for_user(user_id)
            if not path.exists():
                return {}
            found: Dict[str, Any] = {}
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if str(row.get("tree_id", "") or "") != str(tree_id):
                        continue
                    tree = row.get("tree")
                    if isinstance(tree, dict):
                        found = tree
            return found
        except Exception as e:
            logger.debug("ReasoningTreeHistoryStore: load completed tree failed: {}", e)
            return {}

    def list(
        self,
        *,
        user_id: Optional[str],
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return completed reasoning trees persisted for a user/session."""
        try:
            path = self.path_for_user(user_id)
            if not path.exists():
                return []
            latest_by_tree: Dict[str, Dict[str, Any]] = {}
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    tree_id = str(row.get("tree_id", "") or "")
                    if not tree_id:
                        continue
                    if session_id and str(row.get("session_id", "") or "") != str(session_id):
                        continue
                    tree = row.get("tree")
                    if not isinstance(tree, dict):
                        continue
                    latest_by_tree[tree_id] = tree
            rows = list(latest_by_tree.values())
            rows.sort(key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
            return rows[: max(1, int(limit))]
        except Exception as e:
            logger.debug("ReasoningTreeHistoryStore: list completed trees failed: {}", e)
            return []
