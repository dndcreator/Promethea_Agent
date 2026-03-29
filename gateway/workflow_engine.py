from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from .events import EventEmitter
from .protocol import EventType
from .tool_service import ToolInvocationContext
from .workflow_models import (
    Checkpoint,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_WAITING_HUMAN,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_SUCCEEDED,
    STEP_STATUS_WAITING_HUMAN,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
)


class WorkflowError(Exception):
    pass


class WorkflowDependencyError(WorkflowError):
    def __init__(self, dependency: str, detail: str) -> None:
        self.dependency = str(dependency or "unknown")
        self.detail = str(detail or "dependency unavailable")
        super().__init__(f"{self.dependency} unavailable: {self.detail}")


class WorkflowEngine:
    def __init__(
        self,
        *,
        event_emitter: Optional[EventEmitter] = None,
        workspace_service: Optional[Any] = None,
        reasoning_service: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        tool_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.workspace_service = workspace_service
        self.reasoning_service = reasoning_service
        self.memory_service = memory_service
        self.tool_service = tool_service
        self._definitions: Dict[str, WorkflowDefinition] = {}
        self._runs: Dict[str, WorkflowRun] = {}
        self._checkpoints: Dict[str, List[Checkpoint]] = {}

    def define_workflow(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        if not definition.steps:
            raise WorkflowError("workflow must contain at least one step")
        self._normalize_definition(definition)
        self._validate_definition(definition)
        now = datetime.utcnow()
        definition.updated_at = now
        if not definition.created_at:
            definition.created_at = now
        self._definitions[definition.workflow_id] = definition
        return definition

    def _normalize_definition(self, definition: WorkflowDefinition) -> None:
        wft = str(definition.workflow_type or "linear").strip().lower()
        definition.workflow_type = wft or "linear"
        if wft != "linear":
            return
        for idx, step in enumerate(definition.steps):
            if idx == 0:
                step.depends_on = []
                continue
            expected_prev = definition.steps[idx - 1].step_id
            raw_dep = [str(dep).strip() for dep in (step.depends_on or []) if str(dep).strip()]
            if not raw_dep:
                step.depends_on = [expected_prev]

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        return self._definitions.get(str(workflow_id or ""))

    def list_workflows(self, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for definition in self._definitions.values():
            if owner_user_id and definition.owner_user_id and definition.owner_user_id != owner_user_id:
                continue
            rows.append(
                {
                    "workflow_id": definition.workflow_id,
                    "name": definition.name,
                    "workflow_type": definition.workflow_type,
                    "status": definition.status,
                    "owner_user_id": definition.owner_user_id,
                    "step_count": len(definition.steps),
                    "updated_at": definition.updated_at.isoformat() + "Z",
                }
            )
        return sorted(rows, key=lambda r: r["updated_at"], reverse=True)

    def start_workflow(
        self,
        *,
        workflow_id: str,
        session_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        definition = self.get_workflow(workflow_id)
        if not definition:
            raise WorkflowError(f"workflow not found: {workflow_id}")

        run_id = f"wf_run_{uuid4().hex}"
        steps = [WorkflowStep(**step.model_dump()) for step in definition.steps]
        initial_step_id = self._select_next_ready_step_id(steps, workflow_type=definition.workflow_type)
        run_meta = dict(run_metadata or {})
        wft = str(definition.workflow_type or "linear").strip().lower() or "linear"
        run_meta.setdefault("workflow_type", wft)
        run_meta.setdefault("scheduler_mode", self._scheduler_mode_for_type(wft))
        run = WorkflowRun(
            workflow_run_id=run_id,
            workflow_id=definition.workflow_id,
            session_id=str(session_id or "default_session"),
            user_id=str(user_id or "default_user"),
            workspace_id=str(workspace_id or session_id or "default_workspace"),
            status=RUN_STATUS_RUNNING,
            current_step_id=initial_step_id,
            steps=steps,
            run_metadata=run_meta,
        )
        self._runs[run.workflow_run_id] = run
        self._checkpoints.setdefault(run.workflow_run_id, [])

        self._emit(
            EventType.CONVERSATION_STAGE_STARTED,
            {
                "stage": "workflow.start",
                "workflow_id": run.workflow_id,
                "workflow_run_id": run.workflow_run_id,
                "session_id": run.session_id,
                "user_id": run.user_id,
            },
        )

        return self.advance_to_next_step(run.workflow_run_id, run_context=run_context)

    async def start_workflow_async(
        self,
        *,
        workflow_id: str,
        session_id: str,
        user_id: str,
        workspace_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        definition = self.get_workflow(workflow_id)
        if not definition:
            raise WorkflowError(f"workflow not found: {workflow_id}")

        run_id = f"wf_run_{uuid4().hex}"
        steps = [WorkflowStep(**step.model_dump()) for step in definition.steps]
        initial_step_id = self._select_next_ready_step_id(steps, workflow_type=definition.workflow_type)
        run_meta = dict(run_metadata or {})
        wft = str(definition.workflow_type or "linear").strip().lower() or "linear"
        run_meta.setdefault("workflow_type", wft)
        run_meta.setdefault("scheduler_mode", self._scheduler_mode_for_type(wft))
        run = WorkflowRun(
            workflow_run_id=run_id,
            workflow_id=definition.workflow_id,
            session_id=str(session_id or "default_session"),
            user_id=str(user_id or "default_user"),
            workspace_id=str(workspace_id or session_id or "default_workspace"),
            status=RUN_STATUS_RUNNING,
            current_step_id=initial_step_id,
            steps=steps,
            run_metadata=run_meta,
        )
        self._runs[run.workflow_run_id] = run
        self._checkpoints.setdefault(run.workflow_run_id, [])
        self._emit(
            EventType.CONVERSATION_STAGE_STARTED,
            {
                "stage": "workflow.start",
                "workflow_id": run.workflow_id,
                "workflow_run_id": run.workflow_run_id,
                "session_id": run.session_id,
                "user_id": run.user_id,
            },
        )
        return await self.advance_to_next_step_async(run.workflow_run_id, run_context=run_context)

    def get_run(self, workflow_run_id: str) -> Optional[WorkflowRun]:
        return self._runs.get(str(workflow_run_id or ""))

    def list_runs(self, *, user_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for run in self._runs.values():
            if user_id and run.user_id != user_id:
                continue
            rows.append(
                {
                    "workflow_run_id": run.workflow_run_id,
                    "workflow_id": run.workflow_id,
                    "session_id": run.session_id,
                    "user_id": run.user_id,
                    "status": run.status,
                    "current_step_id": run.current_step_id,
                    "started_at": run.started_at.isoformat() + "Z",
                    "updated_at": run.updated_at.isoformat() + "Z",
                }
            )
        rows = sorted(rows, key=lambda r: r["updated_at"], reverse=True)
        return rows[: max(1, int(limit or 20))]

    def pause_workflow(self, workflow_run_id: str) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        if run.status in {RUN_STATUS_COMPLETED, RUN_STATUS_FAILED}:
            return run
        run.status = RUN_STATUS_PAUSED
        run.updated_at = datetime.utcnow()
        self._emit(
            EventType.CONVERSATION_STAGE_FINISHED,
            {
                "stage": "workflow.pause",
                "workflow_run_id": run.workflow_run_id,
                "status": run.status,
                "session_id": run.session_id,
                "user_id": run.user_id,
            },
        )
        return run

    def resume_workflow(self, workflow_run_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        if run.status != RUN_STATUS_PAUSED:
            raise WorkflowError("workflow run is not paused")
        run.status = RUN_STATUS_RUNNING
        run.updated_at = datetime.utcnow()
        return self.advance_to_next_step(workflow_run_id, run_context=run_context)

    async def resume_workflow_async(self, workflow_run_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        if run.status != RUN_STATUS_PAUSED:
            raise WorkflowError("workflow run is not paused")
        run.status = RUN_STATUS_RUNNING
        run.updated_at = datetime.utcnow()
        return await self.advance_to_next_step_async(workflow_run_id, run_context=run_context)

    def retry_step(self, workflow_run_id: str, step_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        step = self._find_step(run, step_id)
        if not step:
            raise WorkflowError(f"step not found: {step_id}")
        if step.status != STEP_STATUS_FAILED:
            raise WorkflowError("only failed step can be retried")

        step.status = STEP_STATUS_PENDING
        step.outputs = {}
        run.status = RUN_STATUS_RUNNING
        run.current_step_id = step.step_id
        run.updated_at = datetime.utcnow()
        return self.advance_to_next_step(workflow_run_id, run_context=run_context)

    async def retry_step_async(self, workflow_run_id: str, step_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        step = self._find_step(run, step_id)
        if not step:
            raise WorkflowError(f"step not found: {step_id}")
        if step.status != STEP_STATUS_FAILED:
            raise WorkflowError("only failed step can be retried")

        step.status = STEP_STATUS_PENDING
        step.outputs = {}
        run.status = RUN_STATUS_RUNNING
        run.current_step_id = step.step_id
        run.updated_at = datetime.utcnow()
        return await self.advance_to_next_step_async(workflow_run_id, run_context=run_context)

    def approve_step(self, workflow_run_id: str, step_id: str, approved_by: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        step = self._find_step(run, step_id)
        if not step:
            raise WorkflowError(f"step not found: {step_id}")
        approvals = run.run_metadata.setdefault("approvals", {})
        approvals[step_id] = {
            "approved_by": approved_by,
            "approved_at": datetime.utcnow().isoformat() + "Z",
        }

        if run.status == RUN_STATUS_WAITING_HUMAN and run.current_step_id == step_id:
            step.status = STEP_STATUS_PENDING
            run.status = RUN_STATUS_RUNNING
            run.updated_at = datetime.utcnow()
            return self.advance_to_next_step(workflow_run_id, run_context=run_context)
        return run

    async def approve_step_async(
        self,
        workflow_run_id: str,
        step_id: str,
        approved_by: str,
        *,
        run_context: Optional[Any] = None,
    ) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        step = self._find_step(run, step_id)
        if not step:
            raise WorkflowError(f"step not found: {step_id}")
        approvals = run.run_metadata.setdefault("approvals", {})
        approvals[step_id] = {
            "approved_by": approved_by,
            "approved_at": datetime.utcnow().isoformat() + "Z",
        }

        if run.status == RUN_STATUS_WAITING_HUMAN and run.current_step_id == step_id:
            step.status = STEP_STATUS_PENDING
            run.status = RUN_STATUS_RUNNING
            run.updated_at = datetime.utcnow()
            return await self.advance_to_next_step_async(workflow_run_id, run_context=run_context)
        return run

    def create_checkpoint(self, workflow_run_id: str, step_id: str, *, run_context: Optional[Any], artifact_refs: Optional[List[Dict[str, Any]]] = None) -> Checkpoint:
        run = self._require_run(workflow_run_id)
        checkpoint = Checkpoint(
            checkpoint_id=f"ckpt_{uuid4().hex}",
            workflow_run_id=run.workflow_run_id,
            step_id=step_id,
            run_context_snapshot=self._safe_dict(run_context),
            reasoning_state_snapshot=self._safe_dict(getattr(run_context, "reasoning_state", None)),
            memory_summary_snapshot=self._safe_dict(getattr(run_context, "memory_bundle", None)),
            workspace_artifact_refs=list(artifact_refs or []),
        )
        self._checkpoints.setdefault(run.workflow_run_id, []).append(checkpoint)
        run.checkpoint_id = checkpoint.checkpoint_id
        run.updated_at = datetime.utcnow()
        return checkpoint

    def list_checkpoints(self, workflow_run_id: str) -> List[Checkpoint]:
        return list(self._checkpoints.get(str(workflow_run_id or ""), []))

    def append_run_observation(self, workflow_run_id: str, observation: Dict[str, Any]) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        observations = run.run_metadata.setdefault("observations", [])
        if not isinstance(observations, list):
            observations = []
            run.run_metadata["observations"] = observations
        observations.append(dict(observation or {}))
        # Keep trace payload bounded for long-lived runs.
        if len(observations) > 200:
            run.run_metadata["observations"] = observations[-200:]
        run.updated_at = datetime.utcnow()
        return run

    async def run_tool_action(
        self,
        *,
        workflow_run_id: Optional[str],
        session_id: str,
        user_id: str,
        tool_type: str,
        service_name: str,
        tool_name: str,
        args: Dict[str, Any],
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.tool_service:
            raise WorkflowError("tool_service unavailable for workflow tool execution")

        req_id = f"workflow_{workflow_run_id or uuid4().hex}"
        ctx = ToolInvocationContext(
            session_id=session_id,
            user_id=user_id,
            source="workflow",
            metadata=dict(metadata or {}),
        )
        result = await self.tool_service.call_tool(
            tool_name=tool_name,
            params={
                "agentType": tool_type or "mcp",
                "service_name": service_name or tool_name,
                "tool_name": tool_name or service_name,
                **dict(args or {}),
            },
            ctx=ctx,
            request_id=req_id,
            run_context=run_context,
            user_config=user_config,
        )
        observation = str(result if isinstance(result, (str, int, float, bool)) else result)
        payload = {
            "kind": "tool",
            "tool_type": tool_type,
            "service_name": service_name,
            "tool_name": tool_name,
            "args": dict(args or {}),
            "result": result,
            "observation": observation,
            "at": datetime.utcnow().isoformat() + "Z",
            "workflow_managed": True,
        }
        if workflow_run_id:
            try:
                run = self.append_run_observation(workflow_run_id, payload)
                step = self._current_step(run)
                if step and step.step_type == "tool_step":
                    step.outputs.update(payload)
                    step.status = STEP_STATUS_SUCCEEDED
                    run.updated_at = datetime.utcnow()
            except Exception:
                pass
        return payload

    def advance_to_next_step(self, workflow_run_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        return self._run_async_blocking(self.advance_to_next_step_async(workflow_run_id, run_context=run_context))

    async def advance_to_next_step_async(self, workflow_run_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        if run.status in {RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_PAUSED}:
            return run

        workflow_type = str(run.run_metadata.get("workflow_type") or "linear").strip().lower() or "linear"
        while True:
            ready_steps = self._ready_steps(run, workflow_type=workflow_type)
            if not ready_steps:
                if self._has_blocked_pending_steps(run):
                    run.status = RUN_STATUS_FAILED
                    run.updated_at = datetime.utcnow()
                    run.run_metadata["workflow_error"] = "workflow blocked by unresolved dependencies"
                    run.run_metadata["failure"] = {"code": "workflow_blocked", "message": "workflow blocked by unresolved dependencies"}
                    return run
                run.status = RUN_STATUS_COMPLETED
                run.completed_at = datetime.utcnow()
                run.updated_at = run.completed_at
                self._emit(
                    EventType.CONVERSATION_COMPLETE,
                    {
                        "workflow_run_id": run.workflow_run_id,
                        "workflow_id": run.workflow_id,
                        "status": run.status,
                        "session_id": run.session_id,
                        "user_id": run.user_id,
                    },
                )
                return run

            batch = ready_steps[:1] if workflow_type == "linear" else ready_steps
            execution_pairs: List[Tuple[WorkflowStep, str]] = []
            if len(batch) == 1:
                step = batch[0]
                executed = await self._execute_step_async(run, step, run_context=run_context)
                execution_pairs.append((step, executed))
            else:
                import asyncio

                results = await asyncio.gather(
                    *(self._execute_step_async(run, step, run_context=run_context) for step in batch)
                )
                execution_pairs = list(zip(batch, results))

            waiting_steps = [step for step, status in execution_pairs if status == "waiting_human"]
            if waiting_steps:
                step = waiting_steps[0]
                run.status = RUN_STATUS_WAITING_HUMAN
                run.current_step_id = step.step_id
                run.updated_at = datetime.utcnow()
                self.create_checkpoint(run.workflow_run_id, step.step_id, run_context=run_context)
                return run

            failed_steps = [step for step, status in execution_pairs if status == "failed"]
            if failed_steps:
                step = failed_steps[0]
                run.status = RUN_STATUS_FAILED
                run.current_step_id = step.step_id
                run.updated_at = datetime.utcnow()
                self.create_checkpoint(run.workflow_run_id, step.step_id, run_context=run_context)
                return run

            for step, _status in execution_pairs:
                self.create_checkpoint(
                    run.workflow_run_id,
                    step.step_id,
                    run_context=run_context,
                    artifact_refs=step.outputs.get("artifact_refs") if isinstance(step.outputs, dict) else None,
                )
            self._refresh_run_cursor(run, workflow_type=workflow_type)

    def _execute_step(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> str:
        return self._run_async_blocking(self._execute_step_async(run, step, run_context=run_context))

    async def _execute_step_async(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> str:
        step.status = STEP_STATUS_RUNNING
        step.outputs = step.outputs or {}

        if step.requires_human_approval or step.step_type == "approval_step":
            approvals = run.run_metadata.get("approvals", {})
            if step.step_id not in approvals:
                step.status = STEP_STATUS_WAITING_HUMAN
                step.outputs["waiting_reason"] = "human_approval_required"
                self._emit(
                    EventType.CONVERSATION_STAGE_STARTED,
                    {
                        "stage": "workflow.approval.waiting",
                        "workflow_run_id": run.workflow_run_id,
                        "step_id": step.step_id,
                        "session_id": run.session_id,
                        "user_id": run.user_id,
                    },
                )
                return "waiting_human"
            step.outputs["approval"] = approvals.get(step.step_id)

        try:
            if step.step_type == "reasoning_step":
                step.outputs.update(self._execute_reasoning_step(run, step, run_context=run_context))
            elif step.step_type == "artifact_step":
                step.outputs.update(self._execute_artifact_step(run, step, run_context=run_context))
            elif step.step_type == "memory_step":
                step.outputs.update(self._execute_memory_step(run, step))
            elif step.step_type == "tool_step":
                step.outputs.update(await self._execute_tool_step_async(run, step, run_context=run_context))
            elif step.step_type == "summary_step":
                step.outputs.update({"summary": step.inputs.get("summary") or f"workflow {run.workflow_id} summary"})
            elif step.step_type == "approval_step":
                # approval already validated above; no-op execution.
                step.outputs.update({"approval_passed": True})
            else:
                step.outputs.update({"result": f"step executed: {step.step_type}"})
        except WorkflowDependencyError as e:
            step.status = STEP_STATUS_FAILED
            step.outputs["error"] = str(e)
            step.outputs["error_code"] = "dependency_unavailable"
            step.outputs["dependency"] = e.dependency
            step.outputs["degraded"] = True
            self._emit(
                EventType.CONVERSATION_STAGE_FAILED,
                {
                    "stage": "workflow.step",
                    "workflow_run_id": run.workflow_run_id,
                    "step_id": step.step_id,
                    "error": str(e),
                    "error_code": "dependency_unavailable",
                    "dependency": e.dependency,
                    "session_id": run.session_id,
                    "user_id": run.user_id,
                },
            )
            return "failed"
        except Exception as e:
            step.status = STEP_STATUS_FAILED
            step.outputs["error"] = str(e)
            self._emit(
                EventType.CONVERSATION_STAGE_FAILED,
                {
                    "stage": "workflow.step",
                    "workflow_run_id": run.workflow_run_id,
                    "step_id": step.step_id,
                    "error": str(e),
                    "session_id": run.session_id,
                    "user_id": run.user_id,
                },
            )
            return "failed"

        step.status = STEP_STATUS_SUCCEEDED
        return "succeeded"

    def _execute_reasoning_step(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> Dict[str, Any]:
        reasoning_snapshot = self._safe_dict(getattr(run_context, "reasoning_state", None))
        if not reasoning_snapshot and self.reasoning_service:
            reasoning_snapshot = {"source": "reasoning_service", "mode": "workflow"}
        return {
            "reasoning_state": reasoning_snapshot,
            "reasoning_note": step.inputs.get("goal") or step.description or "workflow reasoning step",
        }

    def _execute_artifact_step(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> Dict[str, Any]:
        path = str(step.inputs.get("path") or f"workflows/{run.workflow_run_id}/{step.step_id}.md")
        content = str(step.inputs.get("content") or f"# Artifact from {step.step_id}\n")
        artifact_refs: List[Dict[str, Any]] = []

        if self.workspace_service:
            handle = self.workspace_service.resolve_workspace_handle(
                user_id=run.user_id,
                workspace_id=run.workspace_id,
            )
            row = self.workspace_service.create_document(
                handle=handle,
                relative_path=path,
                content=content,
                trace_id=str(getattr(run_context, "trace_id", "")) if run_context else None,
                request_id=str(getattr(run_context, "request_id", "")) if run_context else None,
                session_id=run.session_id,
            )
            artifact_refs.append(row)
        else:
            artifact_refs.append({"path": path, "size": len(content), "operation": "create"})
            return {
                "artifact_path": path,
                "artifact_refs": artifact_refs,
                "degraded": True,
                "degrade_reason": "workspace_service_unavailable",
            }

        return {
            "artifact_path": path,
            "artifact_refs": artifact_refs,
        }

    def _execute_memory_step(self, run: WorkflowRun, step: WorkflowStep) -> Dict[str, Any]:
        summary = str(step.inputs.get("summary") or f"workflow run {run.workflow_run_id} completed step {step.step_id}")
        wrote = False
        degraded = False
        degrade_reason = ""
        if self.memory_service and hasattr(self.memory_service, "record_workflow_summary"):
            try:
                self.memory_service.record_workflow_summary(
                    user_id=run.user_id,
                    session_id=run.session_id,
                    workflow_id=run.workflow_id,
                    summary=summary,
                )
                wrote = True
            except Exception:
                wrote = False
                degraded = True
                degrade_reason = "memory_write_failed"
        else:
            degraded = True
            degrade_reason = "memory_service_unavailable"
        return {
            "memory_summary": summary,
            "memory_write_gate": "delegated",
            "memory_written": wrote,
            "degraded": degraded,
            "degrade_reason": degrade_reason,
        }

    def _execute_tool_step(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> Dict[str, Any]:
        return self._run_async_blocking(self._execute_tool_step_async(run, step, run_context=run_context))

    async def _execute_tool_step_async(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> Dict[str, Any]:
        if not self.tool_service:
            raise WorkflowDependencyError("tool_service", "tool_step requires tool service")

        inputs = dict(step.inputs or {})
        tool_type = str(inputs.get("tool_type") or inputs.get("agentType") or "mcp").strip() or "mcp"
        service_name = str(inputs.get("service_name") or inputs.get("service") or "").strip()
        tool_name = str(inputs.get("tool_name") or inputs.get("command") or "").strip()
        args = inputs.get("args")
        if not isinstance(args, dict):
            args = {
                k: v
                for k, v in inputs.items()
                if k not in {"tool_type", "agentType", "service_name", "service", "tool_name", "command", "args"}
            }
        if not service_name:
            service_name = tool_name
        if not tool_name:
            tool_name = service_name
        if not tool_name:
            raise WorkflowError("tool_step requires tool_name or service_name")

        user_cfg = {}
        if run_context is not None:
            user_cfg = getattr(run_context, "user_config", None) or {}
        if not isinstance(user_cfg, dict):
            user_cfg = {}

        payload = await self.run_tool_action(
            workflow_run_id=run.workflow_run_id,
            session_id=run.session_id,
            user_id=run.user_id,
            tool_type=tool_type,
            service_name=service_name,
            tool_name=tool_name,
            args=dict(args or {}),
            run_context=run_context,
            user_config=user_cfg,
            metadata={"source": "workflow_step", "step_id": step.step_id},
        )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    def _move_to_next_step(self, run: WorkflowRun, completed_step_id: str) -> None:
        _ = completed_step_id
        workflow_type = str(run.run_metadata.get("workflow_type") or "linear").strip().lower() or "linear"
        run.current_step_id = self._select_next_ready_step_id(run.steps, workflow_type=workflow_type)
        run.status = RUN_STATUS_RUNNING if run.current_step_id else RUN_STATUS_COMPLETED
        run.updated_at = datetime.utcnow()
        if run.current_step_id is None:
            run.completed_at = run.updated_at

    def _current_step(self, run: WorkflowRun) -> Optional[WorkflowStep]:
        if run.current_step_id:
            for step in run.steps:
                if (
                    step.step_id == run.current_step_id
                    and step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING}
                    and self._dependencies_satisfied(step, run.steps)
                ):
                    return step
        for step in run.steps:
            if step.status in {STEP_STATUS_WAITING_HUMAN, STEP_STATUS_FAILED}:
                return step
        for step in run.steps:
            if step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING} and self._dependencies_satisfied(step, run.steps):
                return step
        return None

    def _ready_steps(self, run: WorkflowRun, *, workflow_type: str) -> List[WorkflowStep]:
        ready: List[WorkflowStep] = []
        for step in run.steps:
            if step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING} and self._dependencies_satisfied(step, run.steps):
                ready.append(step)
        if not ready:
            return []
        if workflow_type == "linear":
            return ready[:1]
        return ready

    def _refresh_run_cursor(self, run: WorkflowRun, *, workflow_type: str) -> None:
        run.current_step_id = self._select_next_ready_step_id(run.steps, workflow_type=workflow_type)
        run.status = RUN_STATUS_RUNNING if run.current_step_id else RUN_STATUS_COMPLETED
        run.updated_at = datetime.utcnow()
        if run.current_step_id is None:
            run.completed_at = run.updated_at

    def _find_step(self, run: WorkflowRun, step_id: str) -> Optional[WorkflowStep]:
        sid = str(step_id or "")
        for step in run.steps:
            if step.step_id == sid:
                return step
        return None

    def _require_run(self, workflow_run_id: str) -> WorkflowRun:
        run = self.get_run(workflow_run_id)
        if not run:
            raise WorkflowError(f"workflow run not found: {workflow_run_id}")
        return run

    def _validate_definition(self, definition: WorkflowDefinition) -> None:
        allowed_types = {"linear", "dag", "graph", "parallel"}
        wft = str(definition.workflow_type or "linear").strip().lower()
        if wft not in allowed_types:
            raise WorkflowError(f"unsupported workflow_type: {definition.workflow_type}")
        step_ids: Set[str] = set()
        for step in definition.steps:
            sid = str(step.step_id or "").strip()
            if not sid:
                raise WorkflowError("step_id is required")
            if sid in step_ids:
                raise WorkflowError(f"duplicate step_id: {sid}")
            step_ids.add(sid)
        for step in definition.steps:
            for dep in step.depends_on:
                d = str(dep or "").strip()
                if not d:
                    continue
                if d == step.step_id:
                    raise WorkflowError(f"step cannot depend on itself: {step.step_id}")
                if d not in step_ids:
                    raise WorkflowError(f"unknown dependency '{d}' for step '{step.step_id}'")
        if wft == "linear":
            for idx, step in enumerate(definition.steps):
                expected_dep = [] if idx == 0 else [definition.steps[idx - 1].step_id]
                actual_dep = [str(dep).strip() for dep in step.depends_on if str(dep).strip()]
                if actual_dep != expected_dep:
                    raise WorkflowError(
                        f"linear workflow requires explicit sequential dependencies; "
                        f"step '{step.step_id}' expected depends_on={expected_dep}, got {actual_dep}"
                    )
        else:
            self._ensure_acyclic_definition(definition)

    def _ensure_acyclic_definition(self, definition: WorkflowDefinition) -> None:
        deps: Dict[str, List[str]] = {}
        for step in definition.steps:
            deps[step.step_id] = [str(dep).strip() for dep in step.depends_on if str(dep).strip()]
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def _dfs(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise WorkflowError(f"workflow contains dependency cycle at step '{step_id}'")
            visiting.add(step_id)
            for dep in deps.get(step_id, []):
                _dfs(dep)
            visiting.remove(step_id)
            visited.add(step_id)

        for sid in deps.keys():
            _dfs(sid)

    @staticmethod
    def _scheduler_mode_for_type(workflow_type: str) -> str:
        wft = str(workflow_type or "linear").strip().lower()
        if wft == "linear":
            return "sequential"
        if wft == "parallel":
            return "dependency_batch"
        if wft in {"dag", "graph"}:
            return "dependency_graph"
        return "unknown"

    @staticmethod
    def _dependencies_satisfied(step: WorkflowStep, all_steps: List[WorkflowStep]) -> bool:
        if not step.depends_on:
            return True
        status_by_id = {s.step_id: s.status for s in all_steps}
        for dep in step.depends_on:
            if status_by_id.get(dep) not in {STEP_STATUS_SUCCEEDED, STEP_STATUS_SKIPPED}:
                return False
        return True

    def _select_next_ready_step_id(self, steps: List[WorkflowStep], *, workflow_type: str = "linear") -> Optional[str]:
        ready: List[WorkflowStep] = []
        for step in steps:
            if step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING} and self._dependencies_satisfied(step, steps):
                ready.append(step)
        if not ready:
            return None
        if workflow_type == "linear":
            return ready[0].step_id
        ready_sorted = sorted(ready, key=lambda s: s.step_id)
        return ready_sorted[0].step_id

    def _has_blocked_pending_steps(self, run: WorkflowRun) -> bool:
        for step in run.steps:
            if step.status == STEP_STATUS_PENDING and not self._dependencies_satisfied(step, run.steps):
                return True
        return False

    @staticmethod
    def _run_async_blocking(coro: Any) -> Any:
        import asyncio
        import threading

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result_box: Dict[str, Any] = {}
        error_box: Dict[str, Any] = {}

        def _runner() -> None:
            try:
                result_box["value"] = asyncio.run(coro)
            except Exception as exc:  # pragma: no cover
                error_box["error"] = exc

        th = threading.Thread(target=_runner, daemon=True)
        th.start()
        th.join()
        if "error" in error_box:
            raise error_box["error"]
        return result_box.get("value")

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return deepcopy(value)
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump()
                return dumped if isinstance(dumped, dict) else {"value": dumped}
            except Exception:
                return {}
        return {"value": value}

    def _emit(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return

        import asyncio

        async def _emit_event() -> None:
            await self.event_emitter.emit(event_type, payload)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit_event())
        except Exception:
            pass





