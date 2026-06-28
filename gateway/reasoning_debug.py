from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from config import config as global_config

from .reasoning_models import ReasoningTree
from .reasoning_utils import safe_user_segment


class ReasoningDebugSnapshotWriter:
    """Optional debug trace writer for reasoning trees."""

    async def write(
        self,
        tree: ReasoningTree,
        *,
        user_id: str,
        policy: Dict[str, Any],
    ) -> None:
        if not policy.get("debug_log"):
            return
        try:
            user_dir = Path(global_config.system.log_dir) / safe_user_segment(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d")
            path = user_dir / f"{day}.reasoning.jsonl"
            payload = {
                "timestamp": time.time(),
                "tree": {
                    "tree_id": tree.tree_id,
                    "session_id": tree.session_id,
                    "user_id": tree.user_id,
                    "root_goal": tree.root_goal,
                    "status": tree.status,
                    "created_at": tree.created_at,
                    "updated_at": tree.updated_at,
                    "stats": tree.stats,
                    "root_node_id": tree.root_node_id,
                    "nodes": [asdict(node) for node in tree.nodes.values()],
                },
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("Reasoning debug snapshot failed: {}", e)
