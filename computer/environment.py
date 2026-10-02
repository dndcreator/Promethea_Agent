"""Persistent workspace environments managed inside the computer runtime."""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agentkit.security.process_sandbox import SandboxedProcessRunner
from agentkit.security.sandbox import get_sandbox_policy

from .base import ComputerCapability, ComputerController, ComputerResult
from .execution_context import current_workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EnvironmentController(ComputerController):
    """Own resumable canvas records and their sandboxed child processes."""

    def __init__(self, workspace_root: Optional[str] = None):
        super().__init__("Environment", ComputerCapability.ENVIRONMENT)
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.state_dir = self.workspace_root / ".promethea"
        self.state_path = self.state_dir / "environments.json"
        self.environments: Dict[str, Dict[str, Any]] = {}
        self.processes: Dict[str, Any] = {}
        self._lifecycle_events: List[Dict[str, Any]] = []
        self.sandbox = get_sandbox_policy()

    async def initialize(self) -> bool:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                rows = payload.get("environments", {}) if isinstance(payload, dict) else {}
                self.environments = {str(key): dict(value) for key, value in rows.items() if isinstance(value, dict)}
            except (OSError, ValueError):
                self.environments = {}
        changed = False
        for row in self.environments.values():
            if "command" in row:
                row.pop("command", None)
                row["revision"] = int(row.get("revision") or 0) + 1
                row["updated_at"] = _now()
                changed = True
            if row.get("kind") == "process" and row.get("status") in {"running", "starting"}:
                row.update(status="interrupted", pid=None, updated_at=_now())
                self._record_event("interrupted", row)
                changed = True
        if changed:
            self._save()
        self.is_initialized = True
        return True

    async def cleanup(self) -> bool:
        for environment_id in list(self.processes):
            await self._stop({"environment_id": environment_id})
        self.is_initialized = False
        return True

    def has_background_activity(self) -> bool:
        return any(process.poll() is None for process in self.processes.values())

    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        handlers = {
            "register": self._register,
            "list": self._list,
            "get": self._get,
            "launch": self._launch,
            "stop": self._stop,
            "remove": self._remove,
        }
        handler = handlers.get(str(action or "").strip().lower())
        if handler is None:
            return ComputerResult(success=False, error=f"Unknown environment action: {action}")
        try:
            result = await handler(dict(params or {}))
            return ComputerResult(
                success=True,
                result=result,
                metadata={"lifecycle_events": self.drain_lifecycle_events()},
            )
        except (KeyError, ValueError, PermissionError, OSError) as exc:
            return ComputerResult(
                success=False,
                error=str(exc),
                metadata={"lifecycle_events": self.drain_lifecycle_events()},
            )

    def get_available_actions(self) -> List[Dict[str, Any]]:
        return [
            {"name": "register", "params": ["name", "kind?", "root", "entrypoint", "port?"]},
            {"name": "list", "params": []},
            {"name": "get", "params": ["environment_id"]},
            {"name": "launch", "params": ["environment_id", "command?", "expected_revision?"]},
            {"name": "stop", "params": ["environment_id"]},
            {"name": "remove", "params": ["environment_id"]},
        ]

    async def _register(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = str(params.get("name") or "").strip()
        if not name:
            raise ValueError("environment name is required")
        if str(params.get("command") or "").strip():
            raise ValueError("environment commands are accepted only by launch")
        kind = str(params.get("kind") or ("process" if params.get("port") else "static")).strip().lower()
        if kind not in {"static", "process"}:
            raise ValueError("environment kind must be static or process")
        root = self._resolve(str(params.get("root") or "."), must_exist=True, directory=True)
        entrypoint = str(params.get("entrypoint") or ("/" if kind == "process" else "index.html")).strip()
        if kind == "static":
            entrypoint_path = (root / entrypoint).resolve()
            self._assert_workspace_path(entrypoint_path)
            if not entrypoint_path.is_file():
                raise FileNotFoundError(f"environment entrypoint not found: {entrypoint}")
        environment_id = str(params.get("environment_id") or f"env_{uuid4().hex}")
        port = params.get("port")
        if port is not None:
            port = int(port)
            if not 1024 <= port <= 65535:
                raise ValueError("environment port is out of range")
        existing = self.environments.get(environment_id) or {}
        if existing.get("status") == "running":
            raise ValueError("running environment must be stopped before registration changes")
        scope = current_workspace()
        now = _now()
        record = {
            "environment_id": environment_id,
            "name": name,
            "kind": kind,
            "root": str(root.relative_to(self.workspace_root)).replace("\\", "/") or ".",
            "entrypoint": entrypoint.replace("\\", "/"),
            "port": port,
            "status": "ready",
            "pid": None,
            "revision": int(existing.get("revision") or 0) + 1,
            "task_id": scope.execution.get("task_id") if scope else None,
            "run_id": scope.execution.get("run_id") if scope else None,
            "session_id": scope.execution.get("session_id") if scope else None,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self.environments[environment_id] = record
        self._save()
        self._record_event("registered", record)
        return self._public(record)

    async def _list(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._refresh_statuses()
        rows = sorted(self.environments.values(), key=lambda item: item.get("updated_at", ""), reverse=True)
        return [self._public(row) for row in rows]

    async def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._refresh_statuses()
        return self._public(self._require(str(params.get("environment_id") or "")))

    async def _launch(self, params: Dict[str, Any]) -> Dict[str, Any]:
        environment_id = str(params.get("environment_id") or "")
        row = self._require(environment_id)
        if row["kind"] == "static":
            row.update(status="running", pid=None, updated_at=_now())
            self._save()
            self._record_event("started", row)
            return self._public(row)
        current = self.processes.get(environment_id)
        if current is not None and current.poll() is None:
            return self._public(row)
        command = str(params.get("command") or "").strip()
        if not command:
            raise ValueError("process environment launch requires command")
        try:
            expected_revision = int(params.get("expected_revision"))
        except (TypeError, ValueError) as exc:
            raise ValueError("process environment launch requires expected_revision") from exc
        if expected_revision != int(row.get("revision") or 0):
            raise ValueError("environment revision changed; inspect it before launch")
        port = int(row.get("port") or 0)
        if not 1024 <= port <= 65535:
            raise ValueError("process environment requires a registered high port")
        if not self._port_available(port):
            raise PermissionError("environment port is already in use")
        root = self._resolve(row["root"], must_exist=True, directory=True)
        decision = self.sandbox.check_command(command, cwd=str(root), workspace_root=self.workspace_root)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked environment command: {decision.reason}")
        process = SandboxedProcessRunner(sandbox=self.sandbox).popen(
            command, shell=True, cwd=str(root), workspace_root=self.workspace_root,
        )
        self.processes[environment_id] = process
        row.update(
            status="running",
            pid=process.pid,
            updated_at=_now(),
            last_command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
        )
        self._save()
        self._record_event("started", row)
        return self._public(row)

    async def _stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        environment_id = str(params.get("environment_id") or "")
        row = self._require(environment_id)
        process = self.processes.pop(environment_id, None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=3)
        row.update(status="stopped", pid=None, updated_at=_now())
        self._save()
        self._record_event("stopped", row)
        return self._public(row)

    async def _remove(self, params: Dict[str, Any]) -> Dict[str, Any]:
        environment_id = str(params.get("environment_id") or "")
        if environment_id in self.processes:
            await self._stop({"environment_id": environment_id})
        removed = self.environments.pop(environment_id, None)
        if removed is None:
            raise KeyError(f"environment not found: {environment_id}")
        self._save()
        self._record_event("removed", removed)
        return {"environment_id": environment_id, "removed": True}

    def _refresh_statuses(self) -> None:
        changed = False
        for environment_id, process in list(self.processes.items()):
            returncode = process.poll()
            if returncode is None:
                continue
            self.processes.pop(environment_id, None)
            row = self.environments.get(environment_id)
            if row:
                row.update(status="stopped" if returncode == 0 else "failed", pid=None, updated_at=_now())
                self._record_event(str(row["status"]), row)
                changed = True
        if changed:
            self._save()

    def _require(self, environment_id: str) -> Dict[str, Any]:
        row = self.environments.get(environment_id)
        if row is None:
            raise KeyError(f"environment not found: {environment_id}")
        return row

    def _resolve(self, relative: str, *, must_exist: bool, directory: bool) -> Path:
        target = (self.workspace_root / str(relative or ".")).resolve()
        self._assert_workspace_path(target)
        if must_exist and not target.exists():
            raise FileNotFoundError(f"environment path not found: {relative}")
        if must_exist and directory != target.is_dir():
            raise ValueError(f"invalid environment path type: {relative}")
        return target

    def _assert_workspace_path(self, target: Path) -> None:
        try:
            target.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError("environment path escapes workspace") from exc

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "environments": self.environments}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def _record_event(self, action: str, row: Dict[str, Any]) -> None:
        self._lifecycle_events.append({
            "action": action,
            "status": row.get("status"),
            **self._public(row),
        })

    def drain_lifecycle_events(self) -> List[Dict[str, Any]]:
        events = self._lifecycle_events
        self._lifecycle_events = []
        return events

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", int(port)))
            except OSError:
                return False
        return True

    @staticmethod
    def _public(row: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in row.items() if key != "command"}
