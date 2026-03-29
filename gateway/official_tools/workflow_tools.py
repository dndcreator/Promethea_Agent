from __future__ import annotations

from typing import Any, Dict, List, Optional

from gateway.tool_service import ToolInvocationContext
from gateway.workflow_models import WorkflowDefinition, WorkflowStep


def _resolve_user_session(
    args: Dict[str, Any],
    ctx: Optional[ToolInvocationContext],
) -> tuple[str, str]:
    user_id = str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip() or "default_user"
    session_id = str((args or {}).get("session_id") or (ctx.session_id if ctx else "") or "default_session").strip() or "default_session"
    return user_id, session_id


class _WorkflowBaseTool:
    official = True
    official_domain = "workflow"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    def _engine(self) -> Any:
        engine = getattr(self.gateway_server, "workflow_engine", None)
        if engine is None:
            raise RuntimeError("workflow_engine unavailable")
        return engine


class WorkflowDefineTool(_WorkflowBaseTool):
    tool_id = "workflow.define"
    name = "workflow.define"
    description = "Define a workflow (linear/dag/parallel/graph)."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        workflow_id = str((args or {}).get("workflow_id") or "").strip()
        name = str((args or {}).get("name") or workflow_id).strip()
        if not workflow_id:
            raise ValueError("workflow_id is required")
        steps_raw = (args or {}).get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("steps must be a non-empty list")
        user_id, _ = _resolve_user_session(args, ctx)
        workflow_type = str((args or {}).get("workflow_type") or "linear").strip() or "linear"
        steps: List[WorkflowStep] = []
        for idx, row in enumerate(steps_raw):
            if not isinstance(row, dict):
                continue
            sid = str(row.get("step_id") or f"step_{idx + 1}")
            stype = str(row.get("step_type") or "tool_step")
            sname = str(row.get("name") or sid)
            step = WorkflowStep(
                step_id=sid,
                step_type=stype,
                name=sname,
                description=str(row.get("description") or ""),
                inputs=dict(row.get("inputs") or {}),
                requires_human_approval=bool(row.get("requires_human_approval", False)),
                depends_on=[str(x) for x in (row.get("depends_on") or []) if str(x).strip()],
                artifact_targets=list(row.get("artifact_targets") or []),
            )
            steps.append(step)
        definition = WorkflowDefinition(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            name=name or workflow_id,
            description=str((args or {}).get("description") or ""),
            owner_user_id=user_id,
            steps=steps,
            policy=dict((args or {}).get("policy") or {}),
        )
        saved = self._engine().define_workflow(definition)
        return {"workflow": saved.model_dump()}


class WorkflowListTool(_WorkflowBaseTool):
    tool_id = "workflow.list"
    name = "workflow.list"
    description = "List workflows for current user."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, _ = _resolve_user_session(args, ctx)
        limit = int((args or {}).get("limit") or 50)
        limit = max(1, min(limit, 500))
        rows = self._engine().list_workflows(owner_user_id=user_id)
        return {"count": min(len(rows), limit), "workflows": rows[:limit]}


class WorkflowStartTool(_WorkflowBaseTool):
    tool_id = "workflow.start"
    name = "workflow.start"
    description = "Start a workflow run."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        workflow_id = str((args or {}).get("workflow_id") or "").strip()
        if not workflow_id:
            raise ValueError("workflow_id is required")
        user_id, session_id = _resolve_user_session(args, ctx)
        workspace_id = str((args or {}).get("workspace_id") or session_id).strip() or session_id
        engine = self._engine()
        kwargs = {
            "workflow_id": workflow_id,
            "session_id": session_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "run_context": args,
            "run_metadata": dict((args or {}).get("run_metadata") or {}),
        }
        start_async = getattr(engine, "start_workflow_async", None)
        if callable(start_async):
            run = await start_async(**kwargs)
        else:
            run = engine.start_workflow(**kwargs)
        return {"run": run.model_dump()}


class WorkflowStatusTool(_WorkflowBaseTool):
    tool_id = "workflow.status"
    name = "workflow.status"
    description = "Get workflow run status."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        if not run_id:
            raise ValueError("workflow_run_id is required")
        run = self._engine().get_run(run_id)
        if run is None:
            raise ValueError("workflow run not found")
        return {"run": run.model_dump()}


class WorkflowListRunsTool(_WorkflowBaseTool):
    tool_id = "workflow.list_runs"
    name = "workflow.list_runs"
    description = "List workflow runs for current user."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, _ = _resolve_user_session(args, ctx)
        limit = int((args or {}).get("limit") or 20)
        limit = max(1, min(limit, 200))
        rows = self._engine().list_runs(user_id=user_id, limit=limit)
        return {"count": len(rows), "runs": rows}


class WorkflowPauseTool(_WorkflowBaseTool):
    tool_id = "workflow.pause"
    name = "workflow.pause"
    description = "Pause a workflow run."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        if not run_id:
            raise ValueError("workflow_run_id is required")
        run = self._engine().pause_workflow(run_id)
        return {"run": run.model_dump()}


class WorkflowResumeTool(_WorkflowBaseTool):
    tool_id = "workflow.resume"
    name = "workflow.resume"
    description = "Resume a paused workflow run."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        if not run_id:
            raise ValueError("workflow_run_id is required")
        engine = self._engine()
        resume_async = getattr(engine, "resume_workflow_async", None)
        if callable(resume_async):
            run = await resume_async(run_id, run_context=args)
        else:
            run = engine.resume_workflow(run_id, run_context=args)
        return {"run": run.model_dump()}


class WorkflowRetryStepTool(_WorkflowBaseTool):
    tool_id = "workflow.retry_step"
    name = "workflow.retry_step"
    description = "Retry a failed workflow step."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        step_id = str((args or {}).get("step_id") or "").strip()
        if not run_id or not step_id:
            raise ValueError("workflow_run_id and step_id are required")
        engine = self._engine()
        retry_async = getattr(engine, "retry_step_async", None)
        if callable(retry_async):
            run = await retry_async(run_id, step_id, run_context=args)
        else:
            run = engine.retry_step(run_id, step_id, run_context=args)
        return {"run": run.model_dump()}


class WorkflowApproveStepTool(_WorkflowBaseTool):
    tool_id = "workflow.approve_step"
    name = "workflow.approve_step"
    description = "Approve a workflow step waiting for human approval."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, _ = _resolve_user_session(args, ctx)
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        step_id = str((args or {}).get("step_id") or "").strip()
        if not run_id or not step_id:
            raise ValueError("workflow_run_id and step_id are required")
        approved_by = str((args or {}).get("approved_by") or user_id).strip() or user_id
        engine = self._engine()
        approve_async = getattr(engine, "approve_step_async", None)
        if callable(approve_async):
            run = await approve_async(run_id, step_id, approved_by=approved_by, run_context=args)
        else:
            run = engine.approve_step(run_id, step_id, approved_by=approved_by, run_context=args)
        return {"run": run.model_dump()}


class WorkflowCheckpointsTool(_WorkflowBaseTool):
    tool_id = "workflow.checkpoints"
    name = "workflow.checkpoints"
    description = "List checkpoints of a workflow run."

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        run_id = str((args or {}).get("workflow_run_id") or "").strip()
        if not run_id:
            raise ValueError("workflow_run_id is required")
        rows = [item.model_dump() for item in self._engine().list_checkpoints(run_id)]
        return {"workflow_run_id": run_id, "count": len(rows), "checkpoints": rows}
