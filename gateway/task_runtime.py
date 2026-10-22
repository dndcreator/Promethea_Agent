"""Detached execution host for durable Task runs."""
from __future__ import annotations

import asyncio
from contextvars import Context
from copy import deepcopy
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
        self._drivers: Dict[str, Any] = {}

    def register_driver(self, run_type: str, driver: Any) -> None:
        if run_type in self._drivers:
            raise ValueError(f"execution driver already registered: {run_type}")
        self._drivers[run_type] = driver

    async def continue_confirmation(self, *, task_id, user_id, run_id, call_id, operation):
        """Reacquire a fenced run for one exact, explicit approval/rejection."""
        task = self._require_task(task_id, user_id)
        run = next((row for row in task["runs"] if row["run_id"] == run_id), None)
        if self._shutting_down or task["status"] in {"paused", "cancelled"} or run is None or run["status"] != "waiting_human" or run_id in self.active_run_ids():
            raise TaskExecutionConflict("run is not available for confirmation")
        pending = deepcopy(run["metadata"].get("pending_action") or {})
        driver = self._drivers.get(run["run_type"])
        if not pending or pending.get("tool_call_id") != call_id or not callable(getattr(driver, "finish", None)):
            raise TaskExecutionConflict("confirmation does not match the pending action")
        token = self.task_service.claim_execution(task_id=task_id, user_id=user_id, run_id=run_id, owner_id=self.runtime_id, lease_seconds=self.lease_seconds)
        pending.setdefault("task_checkpoint", {})["execution_token"] = token
        self._tokens[run_id] = token

        async def continue_run():
            outcome = "interrupted"
            try:
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="running")
                result = await self._run_with_heartbeat(operation(task, run, token, pending), task_id=task_id, user_id=user_id, token=token)
                self.task_service.assert_action_execution(task_id=task_id, user_id=user_id, expected_objective=task["objective"], task_run_id=run_id, execution_token=token)
                settled = driver.finish(task, run, result)
                outcome = settled["status"]
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status=outcome, detail=settled.get("detail"))
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                # Uncertain effects require explicit recovery, not a supervisor retry.
                self.task_service.assert_execution(task_id=task_id, user_id=user_id, token=token)
                outcome = "paused"
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="paused", detail={"error": "confirmation continuation interrupted; inspect checkpoint before resuming"})
                raise
            finally:
                try:
                    self.task_service.settle_execution(task_id=task_id, user_id=user_id, token=token, status=outcome, reason="confirmation_boundary")
                except (KeyError, TaskExecutionConflict):
                    pass

        job = asyncio.create_task(continue_run(), name=f"task-runtime:{run_id}", context=Context())
        self._jobs[run_id] = job
        job.add_done_callback(lambda completed: self._on_done(run_id, completed))
        return await asyncio.shield(job)

    def schedule_run(self, *, task_id: str, user_id: str, run_id: str) -> None:
        if self._shutting_down:
            raise RuntimeError("Task runtime is shutting down")
        task = self._require_task(task_id, user_id)
        if task["status"] in {"paused", "cancelled"}:
            return
        run = next((row for row in task["runs"] if row["run_id"] == run_id), None)
        if not run or run["run_type"] not in self._drivers:
            raise ValueError("run has no registered execution driver")
        pending = [row for row in task["runs"] if row["run_type"] == run["run_type"] and row["status"] in {"pending", "running"}]
        if not pending or pending[0]["run_id"] != run_id or run_id in self.active_run_ids():
            return
        if any(token.get("task_id") == task_id for rid, token in self._tokens.items() if rid in self.active_run_ids()):
            return
        driver = self._drivers[run["run_type"]]
        if not driver.available(task):
            return
        token = self.task_service.claim_execution(task_id=task_id, user_id=user_id, run_id=run_id, owner_id=self.runtime_id, lease_seconds=self.lease_seconds)
        self._tokens[run_id] = token
        job = asyncio.create_task(self._drive_registered(task, run, token, driver), name=f"task-runtime:{run_id}", context=Context())
        self._jobs[run_id] = job
        job.add_done_callback(lambda completed, rid=run_id: self._on_done(rid, completed))

    async def _drive_registered(self, task: Dict[str, Any], run: Dict[str, Any], token: Dict[str, Any], driver: Any) -> None:
        outcome, reason = "interrupted", "runtime_stopped"
        task_id, user_id, run_id = task["task_id"], task["user_id"], run["run_id"]
        try:
            self.task_service.assert_action_execution(task_id=task_id, user_id=user_id, expected_objective=task["objective"], task_run_id=run_id, execution_token=token)
            self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="running")
            result = await self._run_with_heartbeat(driver.run(task, run, token), task_id=task_id, user_id=user_id, token=token)
            self.task_service.assert_action_execution(task_id=task_id, user_id=user_id, expected_objective=task["objective"], task_run_id=run_id, execution_token=token)
            outcome = str(result["status"])
            self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status=outcome, detail=result.get("detail"))
            reason = "run_boundary"
        except asyncio.CancelledError:
            raise
        except TaskExecutionConflict as exc:
            reason = str(exc)
            current = self._require_task(task_id, user_id)
            try:
                self.task_service.assert_execution(task_id=task_id, user_id=user_id, token=token)
                owns_lease = True
            except TaskExecutionConflict:
                owns_lease = False
            if owns_lease and current["status"] not in {"paused", "cancelled"}:
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="paused", detail={"error": reason})
        except Exception as exc:
            logger.exception("Detached {} run {} failed", run["run_type"], run_id)
            outcome, reason = "failed", str(exc)
            current = self._require_task(task_id, user_id)
            if current["status"] not in {"paused", "cancelled"}:
                self.task_service.assert_execution(task_id=task_id, user_id=user_id, token=token)
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="failed", detail={"error": str(exc)})
        finally:
            try:
                self.task_service.settle_execution(task_id=task_id, user_id=user_id, token=token, status=outcome, reason=reason)
            except (KeyError, TaskExecutionConflict):
                pass

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
        for driver in {id(item): item for item in self._drivers.values()}.values():
            recover = getattr(driver, "recover", None)
            if recover is not None:
                recover()
        for run_type in self._drivers:
            for task in self.task_service.execution_tasks(run_type=run_type):
                if task["status"] in {"paused", "cancelled"}:
                    continue
                for run in task["runs"]:
                    if run["run_type"] == run_type and run["status"] in {"pending", "running"} and run["run_id"] not in self.active_run_ids():
                        try:
                            self.schedule_run(task_id=task["task_id"], user_id=task["user_id"], run_id=run["run_id"])
                            recovered += int(run["run_id"] in self.active_run_ids())
                        except TaskExecutionConflict:
                            continue
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
                if run.get("run_type") in self._drivers:
                    job = self._jobs.get(run["run_id"])
                    self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run["run_id"], status="paused")
                    if job and not job.done():
                        job.cancel()
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
            if item.get("run_type") in self._drivers and item["status"] == "paused":
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="pending")
                scheduled += 1
                continue
            if item.get("run_type") in self._drivers and item["status"] == "waiting_human":
                waiting = True
                continue
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
            if task["status"] == TASK_PAUSED and (task.get("metadata") or {}).get("continuable") is True and all(item["status"] in {"completed", "failed", "cancelled"} for item in task["runs"]):
                return self.task_service.transition_task(task_id=task_id, user_id=user_id, status=TASK_WAITING_USER, reason="resume_ready_worker")
            raise ValueError("task has no paused run to resume")
        for item in self._require_task(task_id, user_id)["runs"]:
            if item.get("run_type") in self._drivers and item["status"] == "pending":
                self.schedule_run(task_id=task_id, user_id=user_id, run_id=item["run_id"])
        return self._require_task(task_id, user_id)

    def cancel_task(self, *, task_id: str, user_id: str, reason: str = "user_cancelled", expected_revision: Optional[int] = None) -> Dict[str, Any]:
        task = self._require_task(task_id, user_id)
        self.task_service.assert_revision(task_id=task_id, user_id=user_id, expected_revision=expected_revision)
        for item in task.get("runs", []):
            run_id = str(item.get("run_id") or "")
            if item.get("run_type") in self._drivers and item["status"] not in {"completed", "failed", "cancelled"}:
                self.task_service.update_run(task_id=task_id, user_id=user_id, run_id=run_id, status="cancelled", detail={"cancel_reason": reason})
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
