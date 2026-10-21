from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class MigrationLineageStore:
    """Durable generations for explicit Memory backend migrations."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent / "migrations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "lineage.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _load(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {"version": 1, "active_generation": None, "generations": []}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "active_generation": None, "generations": []}
        return payload if isinstance(payload, dict) else {"version": 1, "active_generation": None, "generations": []}

    def begin(self, *, source_backend: str, target_backend: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load()
        generation_id = f"memgen_{uuid.uuid4().hex}"
        snapshot_path = self.root / f"{generation_id}.mef.json"
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        self._write_json_atomic(snapshot_path, snapshot)
        record = {
            "generation_id": generation_id,
            "parent_generation_id": state.get("active_generation"),
            "source_backend": str(source_backend),
            "target_backend": str(target_backend),
            "status": "prepared",
            "created_at": self._now(),
            "completed_at": None,
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": hashlib.sha256(encoded).hexdigest(),
            "error": None,
        }
        generations = list(state.get("generations") or [])
        generations.append(record)
        state["generations"] = generations
        self._write_json_atomic(self.index_path, state)
        return dict(record)

    def finish(self, generation_id: str, *, status: str, error: Optional[str] = None) -> Dict[str, Any]:
        state = self._load()
        selected: Dict[str, Any] = {}
        for generation in state.get("generations") or []:
            if generation.get("generation_id") != generation_id:
                continue
            generation["status"] = str(status)
            generation["completed_at"] = self._now()
            generation["error"] = str(error) if error else None
            selected = dict(generation)
            break
        if status == "completed":
            state["active_generation"] = generation_id
        self._write_json_atomic(self.index_path, state)
        return selected

    def snapshot(self) -> Dict[str, Any]:
        return self._load()
