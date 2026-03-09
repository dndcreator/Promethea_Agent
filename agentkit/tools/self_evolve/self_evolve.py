"""Self-evolution service focused on controlled agent code evolution workflows."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentkit.security.sandbox import get_sandbox_policy


class SelfEvolveService:
    """Specialized service for self-improvement planning, patching, and validation."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.name = "self_evolve"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_path = self.workspace_root / "memory" / "self_evolve_tasks.json"
        self._sandbox = get_sandbox_policy()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _resolve_workspace_path(self, path_str: str) -> Path:
        if not path_str:
            raise ValueError("path is required")
        path = Path(path_str)
        if not path.is_absolute():
            path = self.workspace_root / path
        path = path.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as e:
            raise PermissionError(f"Path outside workspace is not allowed: {path}") from e
        return path

    def _load_tasks(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return {"tasks": {}}
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("tasks"), dict):
                return raw
            return {"tasks": {}}
        except Exception:
            return {"tasks": {}}

    def _save_tasks(self, state: Dict[str, Any]) -> None:
        self.store_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_task_or_raise(self, task_id: str) -> Dict[str, Any]:
        state = self._load_tasks()
        task = state.get("tasks", {}).get(task_id)
        if not task:
            raise FileNotFoundError(f"task not found: {task_id}")
        return task

    def _update_task(self, task_id: str, updater) -> Dict[str, Any]:
        state = self._load_tasks()
        task = state.get("tasks", {}).get(task_id)
        if not task:
            raise FileNotFoundError(f"task not found: {task_id}")
        updater(task)
        task["updated_at"] = time.time()
        self._save_tasks(state)
        return task

    async def evolve_create_task(
        self,
        goal: str,
        target_files: List[str],
        acceptance_criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not goal or not str(goal).strip():
            raise ValueError("goal is required")
        if not isinstance(target_files, list) or not target_files:
            raise ValueError("target_files must be a non-empty list")

        normalized_files: List[str] = []
        for rel in target_files:
            p = self._resolve_workspace_path(str(rel))
            normalized_files.append(p.relative_to(self.workspace_root).as_posix())

        now = time.time()
        task_id = f"se_{uuid.uuid4().hex}"
        task = {
            "task_id": task_id,
            "goal": str(goal).strip(),
            "target_files": sorted(set(normalized_files)),
            "acceptance_criteria": [str(x) for x in (acceptance_criteria or []) if str(x).strip()],
            "status": "planned",
            "changes": [],
            "validations": [],
            "created_at": now,
            "updated_at": now,
        }

        state = self._load_tasks()
        state.setdefault("tasks", {})[task_id] = task
        self._save_tasks(state)
        return {"ok": True, "task": task}

    async def evolve_get_task(self, task_id: str) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        return {"ok": True, "task": task}

    async def evolve_list_tasks(self, limit: int = 20, status: str = "") -> Dict[str, Any]:
        state = self._load_tasks()
        rows = list(state.get("tasks", {}).values())
        status_filter = str(status or "").strip().lower()
        if status_filter:
            rows = [x for x in rows if str(x.get("status", "")).lower() == status_filter]
        rows = sorted(rows, key=lambda x: float(x.get("updated_at", 0)), reverse=True)
        rows = rows[: max(1, int(limit))]
        return {"ok": True, "total": len(rows), "tasks": rows}

    async def evolve_collect_context(
        self,
        task_id: str,
        max_chars_per_file: int = 4000,
    ) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        out: List[Dict[str, Any]] = []
        cap = max(200, int(max_chars_per_file))

        for rel in task.get("target_files", []):
            p = self._resolve_workspace_path(rel)
            if not p.exists() or not p.is_file():
                out.append({"path": rel, "exists": False, "content": ""})
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            out.append({"path": rel, "exists": True, "content": text[:cap]})

        return {
            "ok": True,
            "task_id": task_id,
            "goal": task.get("goal", ""),
            "context": out,
        }

    async def evolve_apply_patch(
        self,
        task_id: str,
        path: str,
        old: str,
        new: str,
        count: int = 1,
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        if not old:
            raise ValueError("old cannot be empty")

        task = self._get_task_or_raise(task_id)
        rel = self._resolve_workspace_path(path).relative_to(self.workspace_root).as_posix()
        allowed = set(task.get("target_files", []))
        if rel not in allowed:
            raise PermissionError(f"path not declared in task target_files: {rel}")

        file_path = self._resolve_workspace_path(rel)
        path_decision = self._sandbox.check_path(str(file_path), intent="patch", workspace_root=self.workspace_root)
        if not path_decision.allowed:
            raise PermissionError(f"sandbox blocked patch: {path_decision.reason}")
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        text = file_path.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            return {"ok": False, "task_id": task_id, "path": rel, "updated": False, "reason": "old text not found"}

        if create_backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)

        n = max(1, int(count))
        updated_text = text.replace(old, new, n)
        applied = min(n, text.count(old))
        file_path.write_text(updated_text, encoding="utf-8")

        def _append_change(t: Dict[str, Any]) -> None:
            t.setdefault("changes", []).append(
                {
                    "ts": time.time(),
                    "path": rel,
                    "op": "replace",
                    "count": applied,
                    "old_excerpt": old[:120],
                    "new_excerpt": str(new)[:120],
                }
            )
            if t.get("status") == "planned":
                t["status"] = "editing"

        self._update_task(task_id, _append_change)

        return {
            "ok": True,
            "task_id": task_id,
            "path": rel,
            "updated": True,
            "replaced": applied,
        }

    async def evolve_validate(
        self,
        task_id: str,
        command: str,
        cwd: str = ".",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        if not command or not str(command).strip():
            raise ValueError("command cannot be empty")

        self._get_task_or_raise(task_id)
        run_cwd = self._resolve_workspace_path(cwd)
        cmd_decision = self._sandbox.check_command(command, cwd=str(run_cwd), workspace_root=self.workspace_root)
        if not cmd_decision.allowed:
            raise PermissionError(f"sandbox blocked validate command: {cmd_decision.reason}")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(run_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=max(1, int(timeout))
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Validation timed out after {timeout}s")

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        ok = int(proc.returncode) == 0

        def _append_validation(t: Dict[str, Any]) -> None:
            t.setdefault("validations", []).append(
                {
                    "ts": time.time(),
                    "command": command,
                    "cwd": run_cwd.relative_to(self.workspace_root).as_posix(),
                    "returncode": int(proc.returncode),
                    "ok": ok,
                    "stdout": out[:4000],
                    "stderr": err[:4000],
                }
            )
            t["status"] = "validated" if ok else "failed_validation"

        self._update_task(task_id, _append_validation)

        return {
            "ok": ok,
            "task_id": task_id,
            "returncode": int(proc.returncode),
            "stdout": out[:4000],
            "stderr": err[:4000],
        }




