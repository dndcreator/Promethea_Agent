from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .events import EventEmitter
from .protocol import EventType
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


class WorkflowEngine:
    def __init__(
        self,
        *,
        event_emitter: Optional[EventEmitter] = None,
        workspace_service: Optional[Any] = None,
        reasoning_service: Optional[Any] = None,
        memory_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.workspace_service = workspace_service
        self.reasoning_service = reasoning_service
        self.memory_service = memory_service
        self._definitions: Dict[str, WorkflowDefinition] = {}
        self._runs: Dict[str, WorkflowRun] = {}
        self._checkpoints: Dict[str, List[Checkpoint]] = {}

    def define_workflow(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        if not definition.steps:
            raise WorkflowError("workflow must contain at least one step")
        if definition.workflow_type != "linear":
            raise WorkflowError("workflow mvp only supports linear workflow_type")
        now = datetime.utcnow()
        definition.updated_at = now
        if not definition.created_at:
            definition.created_at = now
        self._definitions[definition.workflow_id] = definition
        return definition

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
        run = WorkflowRun(
            workflow_run_id=run_id,
            workflow_id=definition.workflow_id,
            session_id=str(session_id or "default_session"),
            user_id=str(user_id or "default_user"),
            workspace_id=str(workspace_id or session_id or "default_workspace"),
            status=RUN_STATUS_RUNNING,
            current_step_id=steps[0].step_id,
            steps=steps,
            run_metadata=dict(run_metadata or {}),
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

    def advance_to_next_step(self, workflow_run_id: str, *, run_context: Optional[Any] = None) -> WorkflowRun:
        run = self._require_run(workflow_run_id)
        if run.status in {RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_PAUSED}:
            return run

        while True:
            step = self._current_step(run)
            if not step:
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

            if step.status in {STEP_STATUS_SUCCEEDED, STEP_STATUS_SKIPPED}:
                self._move_to_next_step(run, step.step_id)
                continue

            if step.status not in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING, STEP_STATUS_WAITING_HUMAN, STEP_STATUS_FAILED}:
                step.status = STEP_STATUS_PENDING

            executed = self._execute_step(run, step, run_context=run_context)
            if executed == "waiting_human":
                run.status = RUN_STATUS_WAITING_HUMAN
                run.current_step_id = step.step_id
                run.updated_at = datetime.utcnow()
                self.create_checkpoint(run.workflow_run_id, step.step_id, run_context=run_context)
                return run
            if executed == "failed":
                run.status = RUN_STATUS_FAILED
                run.current_step_id = step.step_id
                run.updated_at = datetime.utcnow()
                self.create_checkpoint(run.workflow_run_id, step.step_id, run_context=run_context)
                return run

            self.create_checkpoint(
                run.workflow_run_id,
                step.step_id,
                run_context=run_context,
                artifact_refs=step.outputs.get("artifact_refs") if isinstance(step.outputs, dict) else None,
            )
            self._move_to_next_step(run, step.step_id)

    def _execute_step(self, run: WorkflowRun, step: WorkflowStep, *, run_context: Optional[Any]) -> str:
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
                step.outputs.update({"tool_execution": "stubbed_in_mvp"})
            elif step.step_type == "summary_step":
                step.outputs.update({"summary": step.inputs.get("summary") or f"workflow {run.workflow_id} summary"})
            elif step.step_type == "approval_step":
                # approval already validated above; no-op execution.
                step.outputs.update({"approval_passed": True})
            else:
                step.outputs.update({"result": "step executed in workflow mvp"})
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
        }

    def _execute_memory_step(self, run: WorkflowRun, step: WorkflowStep) -> Dict[str, Any]:
        summary = str(step.inputs.get("summary") or f"workflow run {run.workflow_run_id} completed step {step.step_id}")
        wrote = False
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
        return {
            "memory_summary": summary,
            "memory_write_gate": "delegated",
            "memory_written": wrote,
        }

    def _move_to_next_step(self, run: WorkflowRun, completed_step_id: str) -> None:
        idx = -1
        for i, step in enumerate(run.steps):
            if step.step_id == completed_step_id:
                idx = i
                break
        next_step = run.steps[idx + 1] if idx >= 0 and idx + 1 < len(run.steps) else None
        run.current_step_id = next_step.step_id if next_step else None
        run.status = RUN_STATUS_RUNNING if next_step else RUN_STATUS_COMPLETED
        run.updated_at = datetime.utcnow()
        if next_step is None:
            run.completed_at = run.updated_at

    def _current_step(self, run: WorkflowRun) -> Optional[WorkflowStep]:
        if run.current_step_id:
            for step in run.steps:
                if step.step_id == run.current_step_id:
                    return step
        for step in run.steps:
            if step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING, STEP_STATUS_WAITING_HUMAN, STEP_STATUS_FAILED}:
                return step
        return None

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





