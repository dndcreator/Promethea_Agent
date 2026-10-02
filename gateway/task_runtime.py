"""Detached execution host for durable Task runs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from loguru import logger

from .task_service import TASK_PAUSED, TASK_WAITING_USER, TaskExecutionConflict, TaskService
from .workflow_models import (
    RUN_STATUS_FAILED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_RETRY_WAIT,
    RUN_STATUS_WAITING_HUMAN,
)


class TaskRuntime:
    """Keep workflow-backed Task runs alive independently of client requests."""

    def __init__(self, *, task_service: TaskService, workflow_engine: Any, lease_seconds: float = 30.0) -> None:
        self.task_service = task_service
        self.workflow_engine = workflow_engine
        self.runtime_id = f"task_runtime_{uuid4().hex}"
        self.lease_seconds = max(3.0, float(lease_seconds))
        self._jobs: Dict[str, asyncio.Task] = {}
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._pending: Dict[str, tuple[str, Dict[str, Any]]] = {}
        self._supervisor: Optional[asyncio.Task] = None
        self._shutting_down = False

    def start_workflow(
        self,
        *,
        task_id: Optional[str],
        user_id: str,
        workflow_id: str,
        session_id: str,
        workspace_id: Optional[str] = None,
        run_context: Optional[Dict[str, Any]] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_task_id = str(task_id or "")
        if resolved_task_id:
            task = self.task_service.get_task(resolved_task_id, user_id=user_id) or self._raise_missing(resolved_task_id)
            self.task_service.assert_revision(
                task_id=resolved_task_id, user_id=user_id, expected_revision=expected_revision,
            )
            if str(task.get("status") or "") == "cancelled":
                raise ValueError("cancelled task cannot start a new run")
        else:
            definition = self.workflow_engine.get_workflow(workflow_id)
            if definition is None:
                raise KeyError(f"workflow not found: {workflow_id}")
            task = self.task_service.create_task(
                user_id=user_id,
                title=definition.name,
                objective=definition.description,
                session_id=session_id,
                source="workflow",
            )
            resolved_task_id = str(task["task_id"])
        metadata = dict(run_metadata or {})
        metadata.update({"task_id": resolved_task_id, "execution_owner": "task_runtime"})
        run = self.workflow_engine.prepare_workflow_run(
            workflow_id=workflow_id,
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            run_metadata=metadata,
        )
        self._schedule(run.workflow_run_id, mode="advance", run_context=run_context or {})
        return run.model_dump()

    async def recover_incomplete(self) -> int:
        """Resume runs that were owned by this host when the process stopped."""
        self.task_service.interrupt_orphaned_executions(active_owner_id=self.runtime_id)
        return await self._recover_available()

    def start_supervisor(self) -> None:
        """Continuously adopt due durable work without depending on a client."""
        if self._supervisor is not None and not self._supervisor.done():
            return
        self._supervisor = asyncio.create_task(self._supervise(), name="task-runtime:supervisor")

    async def _recover_available(self) -> int:
        recovered = 0
        for row in self.workflow_engine.list_runs(limit=10000):
            status = str(row.get("status") or "")
            if status not in {RUN_STATUS_RUNNING, RUN_STATUS_RETRY_WAIT}:
                continue
            run_id = str(row.get("workflow_run_id") or "")
            if run_id in self.active_run_ids():
                continue
            run = self.workflow_engine.get_run(run_id)
            if not run or run.run_metadata.get("execution_owner") != "task_runtime":
                continue
            if status == RUN_STATUS_RETRY_WAIT and not self._retry_due(run):
                continue
            context = self.workflow_engine.recovery_context(run_id)
            context.update({"task_id": run.run_metadata.get("task_id"), "run_id": run_id, "recovered": True})
            try:
                if status == RUN_STATUS_RUNNING:
                    self.workflow_engine.repair_interrupted_run(run_id)
                self._schedule(run_id, mode="retry" if status == RUN_STATUS_RETRY_WAIT else "advance", run_context=context)
                recovered += 1
            except TaskExecutionConflict:
                logger.info("Task run {} is still owned by another runtime", run_id)
        return recovered

    async def _supervise(self) -> None:
        while not self._shutting_down:
            try:
                await self._recover_available()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Task recovery supervisor scan failed")
            await asyncio.sleep(2.0)

    @staticmethod
    def _retry_due(run: Any) -> bool:
        retry = run.run_metadata.get("retry") if isinstance(run.run_metadata.get("retry"), dict) else {}
        try:
            due = datetime.fromisoformat(str(retry.get("next_retry_at") or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        return due <= datetime.now(timezone.utc)

    def pause_task(self, *, task_id: str, user_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
        task = self._require_task(task_id, user_id)
        self.task_service.assert_revision(task_id=task_id, user_id=user_id, expected_revision=expected_revision)
        for run in task.get("runs", []):
            if str(run.get("status") or "") in {"pending", "running", "retry_wait"}:
                workflow_run = self.workflow_engine.get_run(str(run.get("run_id") or ""))
                if workflow_run is not None:
                    self.workflow_engine.pause_workflow(workflow_run.workflow_run_id)
        current = self._require_task(task_id, user_id)
        if current.get("status") != TASK_PAUSED:
            current = self.task_service.transition_task(
                task_id=task_id,
                user_id=user_id,
                status=TASK_PAUSED,
                reason="user_pause",
            )
        return current

    def resume_task(self, *, task_id: str, user_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
        task = self._require_task(task_id, user_id)
        self.task_service.assert_revision(task_id=task_id, user_id=user_id, expected_revision=expected_revision)
        scheduled = 0
        waiting = False
        for item in task.get("runs", []):
            run_id = str(item.get("run_id") or "")
            run = self.workflow_engine.get_run(run_id)
            if run is None:
                continue
            if run.status == RUN_STATUS_PAUSED:
                self._schedule(
                    run_id,
                    mode="resume",
                    run_context={**self.workflow_engine.recovery_context(run_id), "task_id": task_id, "run_id": run_id},
                )
                scheduled += 1
            elif run.status == RUN_STATUS_WAITING_HUMAN:
                waiting = True
        if waiting and not scheduled and task.get("status") != TASK_WAITING_USER:
            return self.task_service.transition_task(
                task_id=task_id,
                user_id=user_id,
                status=TASK_WAITING_USER,
                reason="approval_required",
            )
        if not scheduled:
            raise ValueError("task has no paused run to resume")
        return self._require_task(task_id, user_id)

    def cancel_task(self, *, task_id: str, user_id: str, reason: str = "user_cancelled", expected_revision: Optional[int] = None) -> Dict[str, Any]:
        task = self._require_task(task_id, user_id)
        self.task_service.assert_revision(task_id=task_id, user_id=user_id, expected_revision=expected_revision)
        for item in task.get("runs", []):
            run_id = str(item.get("run_id") or "")
            job = self._jobs.get(run_id)
            if job and not job.done():
                job.cancel()
            run = self.workflow_engine.get_run(run_id)
            if run is not None:
                self.workflow_engine.cancel_workflow(run_id, reason=reason)
        current = self._require_task(task_id, user_id)
        if current.get("status") != "cancelled":
            current = self.task_service.transition_task(
                task_id=task_id,
                user_id=user_id,
                status="cancelled",
                reason=reason,
            )
        return current

    def active_run_ids(self) -> List[str]:
        return sorted(run_id for run_id, job in self._jobs.items() if not job.done())

    async def shutdown(self) -> None:
        """Stop process-local workers while leaving persisted runs recoverable."""
        self._shutting_down = True
        if self._supervisor is not None and not self._supervisor.done():
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
        self._supervisor = None
        jobs = [job for job in self._jobs.values() if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self.task_service.interrupt_owned_executions(owner_id=self.runtime_id)
        self._jobs.clear()
        self._tokens.clear()
        self._pending.clear()

    def _schedule(self, run_id: str, *, mode: str, run_context: Dict[str, Any]) -> None:
        existing = self._jobs.get(run_id)
        if existing and not existing.done():
            self._pending[run_id] = (mode, dict(run_context or {}))
            return
        run = self.workflow_engine.get_run(run_id)
        if run is None:
            raise KeyError(f"workflow run not found: {run_id}")
        task_id = str(run.run_metadata.get("task_id") or "")
        if not task_id:
            raise ValueError("detached workflow run is not attached to a Task")
        token = self.task_service.claim_execution(
            task_id=task_id,
            user_id=run.user_id,
            run_id=run_id,
            owner_id=self.runtime_id,
            lease_seconds=self.lease_seconds,
        )
        self._tokens[run_id] = token
        fenced_context = dict(run_context or {})
        fenced_context.update({
            "task_id": task_id,
            "run_id": run_id,
            "execution_token": token,
        })
        job = asyncio.create_task(
            self._drive(run_id, mode=mode, run_context=fenced_context),
            name=f"task-runtime:{run_id}",
        )
        self._jobs[run_id] = job
        job.add_done_callback(lambda completed, rid=run_id: self._on_done(rid, completed))

    async def _drive(self, run_id: str, *, mode: str, run_context: Dict[str, Any]) -> None:
        token = dict(run_context.get("execution_token") or {})
        task_id = str(run_context.get("task_id") or "")
        run = self.workflow_engine.get_run(run_id)
        if run is None:
            return
        outcome = "interrupted"
        reason = "runtime_stopped"
        try:
            if mode == "resume":
                operation = self.workflow_engine.resume_workflow_async(run_id, run_context=run_context)
            elif mode == "retry":
                operation = self.workflow_engine.resume_retry_wait_async(run_id, run_context=run_context)
            else:
                operation = self.workflow_engine.continue_workflow_async(run_id, run_context=run_context)
            result = await self._run_with_heartbeat(
                operation, task_id=task_id, user_id=run.user_id, token=token,
            )
            outcome = str(result.status or "released")
            reason = "run_boundary"
        except asyncio.CancelledError:
            reason = "runtime_cancelled"
            raise
        except TaskExecutionConflict as exc:
            reason = str(exc)
            logger.warning("Detached task run {} lost its execution lease", run_id)
        except Exception as exc:
            logger.exception("Detached task run {} failed", run_id)
            self.workflow_engine.fail_workflow(run_id, error=str(exc))
            outcome = "failed"
            reason = str(exc)
        finally:
            try:
                self.task_service.settle_execution(
                    task_id=task_id, user_id=run.user_id, token=token,
                    status=outcome, reason=reason,
                )
            except (KeyError, TaskExecutionConflict):
                pass

    async def _run_with_heartbeat(
        self,
        operation: Any,
        *,
        task_id: str,
        user_id: str,
        token: Dict[str, Any],
    ) -> Any:
        execution = asyncio.create_task(operation)
        interval = max(1.0, self.lease_seconds / 3.0)
        try:
            while True:
                done, _ = await asyncio.wait({execution}, timeout=interval)
                if execution in done:
                    return await execution
                self.task_service.heartbeat_execution(
                    task_id=task_id, user_id=user_id, token=token, lease_seconds=self.lease_seconds,
                )
        except BaseException:
            if not execution.done():
                execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            raise

    def _on_done(self, run_id: str, job: asyncio.Task) -> None:
        if self._jobs.get(run_id) is job:
            self._jobs.pop(run_id, None)
        self._tokens.pop(run_id, None)
        if self._shutting_down or job.cancelled():
            return
        try:
            job.exception()
        except asyncio.CancelledError:
            return
        pending = self._pending.pop(run_id, None)
        if pending:
            mode, run_context = pending
            self._schedule(run_id, mode=mode, run_context=run_context)

    def _require_task(self, task_id: str, user_id: str) -> Dict[str, Any]:
        task = self.task_service.get_task(task_id, user_id=user_id)
        if task is None:
            self._raise_missing(task_id)
        return task

    @staticmethod
    def _raise_missing(task_id: str) -> None:
        raise KeyError(f"task not found: {task_id}")
