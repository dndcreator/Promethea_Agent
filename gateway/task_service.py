"""Durable task domain, independent from conversations and workflow internals."""
from __future__ import annotations

import json
import os
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .events import EventEmitter
from .protocol import EventType


TASK_OPEN = "open"
TASK_RUNNING = "running"
TASK_WAITING_USER = "waiting_user"
TASK_PAUSED = "paused"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

TASK_TERMINAL = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}
RUN_TERMINAL = {"completed", "failed", "cancelled"}
RUN_ACTIVE = {"pending", "running", "retry_wait"}
RUN_WAITING = {"waiting_human", "waiting_user"}


class TaskRevisionConflict(ValueError):
    """A command targeted an older durable Task revision."""


class TaskExecutionConflict(ValueError):
    """A driver attempted to use an execution lease it no longer owns."""

_TASK_TRANSITIONS = {
    TASK_OPEN: {TASK_RUNNING, TASK_PAUSED, TASK_COMPLETED, TASK_CANCELLED},
    TASK_RUNNING: {TASK_WAITING_USER, TASK_PAUSED, TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED},
    TASK_WAITING_USER: {TASK_RUNNING, TASK_PAUSED, TASK_FAILED, TASK_CANCELLED},
    TASK_PAUSED: {TASK_RUNNING, TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED},
    TASK_COMPLETED: {TASK_RUNNING},
    TASK_FAILED: {TASK_RUNNING, TASK_CANCELLED},
    TASK_CANCELLED: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1.0, float(seconds)))).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class TaskService:
    """Own user goals, durable runs, and their execution-independent event log."""

    def __init__(self, *, storage_path: Optional[str] = None, event_emitter: Optional[EventEmitter] = None) -> None:
        default = Path(__file__).resolve().parent / "task_state.json"
        self.storage_path = Path(storage_path) if storage_path else default
        self.event_emitter = event_emitter
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def create_task(self, *, user_id: str, title: str, objective: str = "", session_id: Optional[str] = None, source: str = "user") -> Dict[str, Any]:
        task_id = f"task_{uuid4().hex}"
        now = _now()
        task = {"task_id": task_id, "user_id": str(user_id), "title": str(title).strip() or "Untitled task", "objective": str(objective).strip(), "session_ids": [str(session_id)] if session_id else [], "status": TASK_OPEN, "revision": 1, "activation_epoch": 0, "executions": {}, "source": source, "runs": [], "created_at": now, "updated_at": now, "completed_at": None}
        self._tasks[task_id] = task
        event = self._record(task_id, "task.created", {"source": source})
        self._persist()
        self._publish(EventType.TASK_CREATED, event)
        return self._copy(task)

    def get_task(self, task_id: str, *, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(str(task_id))
        if not task or (user_id and task.get("user_id") != str(user_id)):
            return None
        out = self._copy(task)
        out["events"] = self.list_events(task_id, user_id=user_id)
        return out

    def assert_revision(self, *, task_id: str, user_id: str, expected_revision: Optional[int]) -> None:
        self._assert_revision(self._require(task_id, user_id), expected_revision)

    def list_tasks(self, *, user_id: str, status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        rows = [self._copy(task) for task in self._tasks.values() if task.get("user_id") == str(user_id)]
        if status:
            rows = [task for task in rows if task.get("status") == status]
        return sorted(rows, key=lambda task: str(task.get("updated_at") or ""), reverse=True)[:max(1, limit)]

    def start_run(self, *, task_id: str, user_id: str, run_id: str, run_type: str, session_id: Optional[str] = None, trace_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        if self._normalize_task_status(task.get("status")) == TASK_CANCELLED:
            raise ValueError("cancelled task cannot start a new run")
        for run in task["runs"]:
            if run.get("run_id") == run_id:
                return self._copy(run)
        run = {"run_id": str(run_id), "run_type": str(run_type), "status": "running", "session_id": str(session_id or ""), "trace_id": str(trace_id or ""), "metadata": dict(metadata or {}), "attempts": [], "started_at": _now(), "updated_at": _now(), "ended_at": None}
        task["runs"].append(run)
        self._attach_session(task, session_id)
        previous_status = self._normalize_task_status(task.get("status"))
        task["status"] = TASK_RUNNING
        task["completed_at"] = None
        task["updated_at"] = _now()
        self._advance_revision(task)
        event = self._record(task_id, "task.run.started", {"run_id": run_id, "run_type": run_type})
        state_event = None
        if previous_status != TASK_RUNNING:
            state_event = self._record(
                task_id,
                "task.state.changed",
                {"from_status": previous_status, "to_status": TASK_RUNNING, "reason": "run_started"},
            )
        self._persist()
        self._publish(EventType.TASK_RUN_STARTED, event)
        if state_event:
            self._publish(EventType.TASK_STATE_CHANGED, state_event)
        return self._copy(run)

    def update_run(self, *, task_id: str, user_id: str, run_id: str, status: str, detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        run = next((item for item in task["runs"] if item.get("run_id") == str(run_id)), None)
        if run is None:
            raise KeyError(f"task run not found: {run_id}")
        run["status"] = str(status)
        run["updated_at"] = _now()
        if status in RUN_TERMINAL:
            run["ended_at"] = run["updated_at"]
        if detail:
            run["metadata"].update(detail)
        previous_status = self._normalize_task_status(task.get("status"))
        next_status = self._derive_task_status(task["runs"], fallback=previous_status)
        task["status"] = next_status
        if next_status == TASK_COMPLETED:
            task["completed_at"] = _now()
        elif next_status not in TASK_TERMINAL:
            task["completed_at"] = None
        task["updated_at"] = _now()
        self._advance_revision(task)
        event = self._record(task_id, "task.run.updated", {"run_id": run_id, "status": status, **dict(detail or {})})
        state_event = None
        if previous_status != next_status:
            state_event = self._record(
                task_id,
                "task.state.changed",
                {"from_status": previous_status, "to_status": next_status, "reason": "run_state_changed"},
            )
        self._persist()
        self._publish(EventType.TASK_RUN_UPDATED, event)
        if state_event:
            self._publish(EventType.TASK_STATE_CHANGED, state_event)
        return self._copy(run)

    def transition_task(
        self,
        *,
        task_id: str,
        user_id: str,
        status: str,
        reason: str = "user_command",
        metadata: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        self._assert_revision(task, expected_revision)
        current = self._normalize_task_status(task.get("status"))
        target = self._normalize_task_status(status)
        if current == target:
            return self._copy(task)
        if target not in _TASK_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid task transition: {current} -> {target}")

        now = _now()
        task["status"] = target
        task["updated_at"] = now
        task["completed_at"] = now if target == TASK_COMPLETED else None
        self._advance_revision(task)
        event = self._record(
            task_id,
            "task.state.changed",
            {
                "from_status": current,
                "to_status": target,
                "reason": str(reason or "user_command"),
                **dict(metadata or {}),
            },
        )
        self._persist()
        self._publish(EventType.TASK_STATE_CHANGED, event)
        return self._copy(task)

    def update_task(
        self,
        *,
        task_id: str,
        user_id: str,
        title: Optional[str] = None,
        objective: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        self._assert_revision(task, expected_revision)
        changes: Dict[str, Any] = {}
        if title is not None:
            resolved = str(title).strip()
            if not resolved:
                raise ValueError("task title cannot be empty")
            task["title"] = resolved
            changes["title"] = resolved
        if objective is not None:
            task["objective"] = str(objective).strip()
            changes["objective"] = task["objective"]
        if not changes:
            return self._copy(task)
        task["updated_at"] = _now()
        self._advance_revision(task)
        self._record(task_id, "task.updated", {"fields": sorted(changes)})
        self._persist()
        return self._copy(task)

    def claim_execution(
        self,
        *,
        task_id: str,
        user_id: str,
        run_id: str,
        owner_id: str,
        lease_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """Claim one fenced execution generation and open a durable attempt."""
        task = self._require(task_id, user_id)
        run = self._require_run(task, run_id)
        executions = task.setdefault("executions", {})
        current = executions.get(str(run_id)) if isinstance(executions, dict) else None
        if current and not self._execution_expired(current):
            if current.get("owner_id") == str(owner_id) and current.get("run_id") == str(run_id):
                return self._copy(current)
            raise TaskExecutionConflict(f"task execution is owned by {current.get('owner_id')}")

        if current:
            self._close_attempt(task, current, status="interrupted", reason="lease_expired")

        now = _now()
        epoch = int(task.get("activation_epoch") or 0) + 1
        attempt_id = f"task_attempt_{uuid4().hex}"
        execution = {
            "task_id": str(task_id),
            "run_id": str(run_id),
            "owner_id": str(owner_id),
            "epoch": epoch,
            "attempt_id": attempt_id,
            "acquired_at": now,
            "heartbeat_at": now,
            "expires_at": _after(lease_seconds),
        }
        task["activation_epoch"] = epoch
        executions[str(run_id)] = execution
        run.setdefault("attempts", []).append({
            "attempt_id": attempt_id,
            "epoch": epoch,
            "owner_id": str(owner_id),
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "ended_at": None,
            "reason": None,
        })
        run["updated_at"] = now
        task["updated_at"] = now
        self._advance_revision(task)
        event = self._record(task_id, "task.execution.claimed", {
            "run_id": run_id, "attempt_id": attempt_id, "owner_id": owner_id, "epoch": epoch,
        })
        self._persist()
        self._publish(EventType.TASK_EXECUTION_CLAIMED, event)
        return self._copy(execution)

    def heartbeat_execution(self, *, task_id: str, user_id: str, token: Dict[str, Any], lease_seconds: float = 30.0) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        execution = self._assert_execution_token(task, token)
        execution["heartbeat_at"] = _now()
        execution["expires_at"] = _after(lease_seconds)
        self._persist()
        return self._copy(execution)

    def assert_execution(self, *, task_id: str, user_id: str, token: Dict[str, Any]) -> None:
        task = self._require(task_id, user_id)
        self._assert_execution_token(task, token)

    def settle_execution(
        self,
        *,
        task_id: str,
        user_id: str,
        token: Dict[str, Any],
        status: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        task = self._require(task_id, user_id)
        execution = self._assert_execution_token(task, token, allow_expired=True)
        self._close_attempt(task, execution, status=str(status), reason=str(reason or ""))
        task.setdefault("executions", {}).pop(str(execution.get("run_id") or ""), None)
        task["updated_at"] = _now()
        self._advance_revision(task)
        event = self._record(task_id, "task.execution.settled", {
            "run_id": execution.get("run_id"), "attempt_id": execution.get("attempt_id"),
            "owner_id": execution.get("owner_id"), "epoch": execution.get("epoch"),
            "status": str(status), "reason": str(reason or ""),
        })
        self._persist()
        self._publish(EventType.TASK_EXECUTION_SETTLED, event)
        return self._copy(task)

    def interrupt_owned_executions(self, *, owner_id: str, reason: str = "runtime_shutdown") -> int:
        """Close this process's attempts without changing the Task business phase."""
        changed = 0
        for task_id, task in self._tasks.items():
            executions = task.get("executions") if isinstance(task.get("executions"), dict) else {}
            for run_id, execution in list(executions.items()):
                if not isinstance(execution, dict) or execution.get("owner_id") != str(owner_id):
                    continue
                self._close_attempt(task, execution, status="interrupted", reason=reason)
                executions.pop(run_id, None)
                task["updated_at"] = _now()
                self._advance_revision(task)
                self._record(task_id, "task.execution.interrupted", {
                    "run_id": execution.get("run_id"), "attempt_id": execution.get("attempt_id"),
                    "owner_id": owner_id, "epoch": execution.get("epoch"), "reason": reason,
                })
                changed += 1
        if changed:
            self._persist()
        return changed

    def interrupt_orphaned_executions(self, *, active_owner_id: str, reason: str = "process_restarted") -> int:
        """Repair leases left by a previous process in the single-host runtime."""
        changed = 0
        for task_id, task in self._tasks.items():
            executions = task.get("executions") if isinstance(task.get("executions"), dict) else {}
            for run_id, execution in list(executions.items()):
                if not isinstance(execution, dict) or execution.get("owner_id") == str(active_owner_id):
                    continue
                self._close_attempt(task, execution, status="interrupted", reason=reason)
                executions.pop(run_id, None)
                task["updated_at"] = _now()
                self._advance_revision(task)
                self._record(task_id, "task.execution.interrupted", {
                    "run_id": execution.get("run_id"), "attempt_id": execution.get("attempt_id"),
                    "owner_id": execution.get("owner_id"), "epoch": execution.get("epoch"), "reason": reason,
                })
                changed += 1
        if changed:
            self._persist()
        return changed

    def export_user_state(self, *, user_id: str) -> Dict[str, Any]:
        tasks = {task_id: self._copy(task) for task_id, task in self._tasks.items() if task.get("user_id") == str(user_id)}
        return {"version": 2, "tasks": tasks, "events": {task_id: self._copy(self._events.get(task_id, [])) for task_id in tasks}}

    def import_user_state(self, *, user_id: str, payload: Dict[str, Any], merge: bool = True) -> Dict[str, int]:
        if not merge:
            self.purge_user_state(user_id)
        imported = 0
        for task_id, task in (payload.get("tasks") or {}).items():
            if not isinstance(task, dict) or str(task.get("user_id")) != str(user_id) or task_id in self._tasks:
                continue
            imported_task = self._copy(task)
            self._normalize_task_record(imported_task)
            self._tasks[str(task_id)] = imported_task
            self._events[str(task_id)] = self._copy((payload.get("events") or {}).get(task_id, []))
            imported += 1
        self._persist()
        return {"tasks": imported}

    def purge_user_state(self, user_id: str) -> Dict[str, int]:
        ids = [task_id for task_id, task in self._tasks.items() if task.get("user_id") == str(user_id)]
        for task_id in ids:
            self._tasks.pop(task_id, None); self._events.pop(task_id, None)
        self._persist()
        return {"tasks": len(ids)}

    def list_events(self, task_id: str, *, user_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if user_id:
            self._require(task_id, user_id)
        return self._copy(self._events.get(str(task_id), [])[-max(1, limit):])

    def _require(self, task_id: str, user_id: str) -> Dict[str, Any]:
        task = self._tasks.get(str(task_id))
        if not task or task.get("user_id") != str(user_id):
            raise KeyError(f"task not found: {task_id}")
        return task

    @staticmethod
    def _require_run(task: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        run = next((item for item in task.get("runs", []) if item.get("run_id") == str(run_id)), None)
        if run is None:
            raise KeyError(f"task run not found: {run_id}")
        return run

    @staticmethod
    def _advance_revision(task: Dict[str, Any]) -> int:
        task["revision"] = max(0, int(task.get("revision") or 0)) + 1
        return task["revision"]

    @staticmethod
    def _assert_revision(task: Dict[str, Any], expected_revision: Optional[int]) -> None:
        if expected_revision is None:
            return
        current = int(task.get("revision") or 0)
        if current != int(expected_revision):
            raise TaskRevisionConflict(f"stale task revision: expected {expected_revision}, current {current}")

    @staticmethod
    def _execution_expired(execution: Dict[str, Any]) -> bool:
        expires_at = _parse_time(execution.get("expires_at"))
        return expires_at is None or expires_at <= datetime.now(timezone.utc)

    def _assert_execution_token(self, task: Dict[str, Any], token: Dict[str, Any], *, allow_expired: bool = False) -> Dict[str, Any]:
        executions = task.get("executions") if isinstance(task.get("executions"), dict) else {}
        execution = executions.get(str(token.get("run_id") or ""))
        if not execution or any(execution.get(key) != token.get(key) for key in ("run_id", "owner_id", "epoch", "attempt_id")):
            raise TaskExecutionConflict("stale task execution token")
        if not allow_expired and self._execution_expired(execution):
            raise TaskExecutionConflict("task execution lease expired")
        return execution

    def _close_attempt(self, task: Dict[str, Any], execution: Dict[str, Any], *, status: str, reason: str) -> None:
        try:
            run = self._require_run(task, str(execution.get("run_id") or ""))
        except KeyError:
            return
        attempt = next((item for item in run.setdefault("attempts", []) if item.get("attempt_id") == execution.get("attempt_id")), None)
        if attempt and attempt.get("status") == "running":
            now = _now()
            attempt.update({"status": status, "reason": reason or None, "updated_at": now, "ended_at": now})
            run["updated_at"] = now

    @classmethod
    def _normalize_task_record(cls, task: Dict[str, Any]) -> None:
        task["status"] = cls._normalize_task_status(task.get("status"))
        task["revision"] = max(1, int(task.get("revision") or 1))
        task["activation_epoch"] = max(0, int(task.get("activation_epoch") or 0))
        executions = task.get("executions") if isinstance(task.get("executions"), dict) else {}
        legacy_execution = task.pop("execution", None)
        if isinstance(legacy_execution, dict) and legacy_execution.get("run_id"):
            executions.setdefault(str(legacy_execution["run_id"]), legacy_execution)
        task["executions"] = executions
        for run in task.get("runs", []):
            if isinstance(run, dict):
                run.setdefault("attempts", [])

    @staticmethod
    def _normalize_task_status(value: Any) -> str:
        status = str(value or TASK_OPEN).strip().lower()
        return TASK_RUNNING if status == "in_progress" else status

    @classmethod
    def _derive_task_status(cls, runs: List[Dict[str, Any]], *, fallback: str) -> str:
        statuses = [str(item.get("status") or "").strip().lower() for item in runs]
        if any(status in RUN_ACTIVE for status in statuses):
            return TASK_RUNNING
        if any(status in RUN_WAITING for status in statuses):
            return TASK_WAITING_USER
        if any(status == "paused" for status in statuses):
            return TASK_PAUSED
        if statuses and all(status in RUN_TERMINAL for status in statuses):
            if any(status == "failed" for status in statuses):
                return TASK_FAILED
            if any(status == "completed" for status in statuses):
                return TASK_COMPLETED
            return TASK_CANCELLED
        return fallback

    def _record(self, task_id: str, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = self._tasks.get(task_id) or {}
        body = {
            "task_id": task_id,
            "user_id": task.get("user_id"),
            "session_id": (task.get("session_ids") or [None])[-1],
            "revision": task.get("revision"),
            **dict(payload),
        }
        event = {"event_id": f"task_event_{uuid4().hex}", "event_type": event_type, "at": _now(), "payload": body}
        self._events.setdefault(task_id, []).append(event)
        return event

    def _publish(self, event_type: EventType, event: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return

        async def publish() -> None:
            await self.event_emitter.emit(event_type, dict(event.get("payload") or {}))

        try:
            asyncio.get_running_loop().create_task(publish())
        except RuntimeError:
            return

    @staticmethod
    def _attach_session(task: Dict[str, Any], session_id: Optional[str]) -> None:
        if session_id and str(session_id) not in task["session_ids"]:
            task["session_ids"].append(str(session_id))

    @staticmethod
    def _copy(value: Any) -> Any:
        return json.loads(json.dumps(value))

    def _load(self) -> None:
        if not self.storage_path.exists(): return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._tasks = raw.get("tasks") if isinstance(raw.get("tasks"), dict) else {}
            self._events = raw.get("events") if isinstance(raw.get("events"), dict) else {}
            for task in self._tasks.values():
                if isinstance(task, dict):
                    self._normalize_task_record(task)
        except Exception as exc:
            raise RuntimeError(f"failed to load durable task state: {self.storage_path}") from exc

    def _persist(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.storage_path.name}.", suffix=".tmp", dir=str(self.storage_path.parent))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 2, "tasks": self._tasks, "events": self._events}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.storage_path)
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
