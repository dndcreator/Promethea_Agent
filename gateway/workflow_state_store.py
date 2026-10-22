"""Workflow durable-state codec and atomic file I/O; no live execution state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional

from .workflow_models import Checkpoint, WorkflowDefinition, WorkflowRun


def snapshot_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        safe_value = json_safe(deepcopy(value))
        return safe_value if isinstance(safe_value, dict) else {"value": safe_value}
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            safe_value = json_safe(dumped)
            return safe_value if isinstance(safe_value, dict) else {"value": safe_value}
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        safe_value = json_safe(vars(value))
        return safe_value if isinstance(safe_value, dict) else {"value": safe_value}
    return {"value": json_safe(value)}


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump(mode="python"))
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    return str(value)


def load_workflow_state(
    path: Path,
) -> tuple[Dict[str, WorkflowDefinition], Dict[str, WorkflowRun], Dict[str, List[Checkpoint]]]:
    if not path.exists():
        return {}, {}, {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"failed to load durable workflow state: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"durable workflow state must be an object: {path}")
    definitions = payload.get("definitions") if isinstance(payload.get("definitions"), dict) else {}
    runs = payload.get("runs") if isinstance(payload.get("runs"), dict) else {}
    checkpoints = payload.get("checkpoints") if isinstance(payload.get("checkpoints"), dict) else {}
    loaded_definitions: Dict[str, WorkflowDefinition] = {}
    for workflow_id, raw in definitions.items():
        try:
            loaded_definitions[str(workflow_id)] = WorkflowDefinition(**raw)
        except Exception as exc:
            raise RuntimeError(f"invalid workflow definition {workflow_id!r} in {path}") from exc
    loaded_runs: Dict[str, WorkflowRun] = {}
    for run_id, raw in runs.items():
        try:
            loaded_runs[str(run_id)] = WorkflowRun(**raw)
        except Exception as exc:
            raise RuntimeError(f"invalid workflow run {run_id!r} in {path}") from exc
    loaded_checkpoints: Dict[str, List[Checkpoint]] = {}
    for run_id, rows in checkpoints.items():
        if not isinstance(rows, list):
            raise RuntimeError(f"invalid workflow checkpoint list {run_id!r} in {path}")
        parsed: List[Checkpoint] = []
        for raw in rows:
            try:
                parsed.append(Checkpoint(**raw))
            except Exception as exc:
                raise RuntimeError(f"invalid workflow checkpoint for {run_id!r} in {path}") from exc
        loaded_checkpoints[str(run_id)] = parsed
    return loaded_definitions, loaded_runs, loaded_checkpoints


def save_workflow_state(
    path: Path,
    *,
    definitions: Dict[str, WorkflowDefinition],
    runs: Dict[str, WorkflowRun],
    checkpoints: Dict[str, List[Checkpoint]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "definitions": {k: json_safe(v.model_dump(mode="python")) for k, v in definitions.items()},
        "runs": {k: json_safe(v.model_dump(mode="python")) for k, v in runs.items()},
        "checkpoints": {
            k: [json_safe(item.model_dump(mode="python")) for item in rows]
            for k, rows in checkpoints.items()
        },
    }
    fd, tmp_file = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_file)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _replace_state_file(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise


def _replace_state_file(tmp_path: Path, path: Path) -> None:
    last_error: Optional[PermissionError] = None
    for _ in range(5):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
