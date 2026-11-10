"""Adapters from internal runtime records to stable public read models."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
from gateway.goal_gaps import GoalGapView, GoalGapState, gap_outcome


def public_pending_confirmation(pending: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(pending, dict) or not pending.get("tool_call_id") or not pending.get("tool_name") or not isinstance(pending.get("args", {}), dict):
        return None
    from .public_contracts import ToolCall
    return ToolCall(tool_call_id=str(pending["tool_call_id"]), tool_name=str(pending["tool_name"]),
                    arguments=dict(pending.get("args") or {}), status="needs_confirmation").model_dump()


def public_pending_input(checkpoint: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from .public_contracts import InputRequest

    pending = (checkpoint or {}).get("pending_input")
    if not pending:
        return None
    return InputRequest.model_validate({key: pending[key] for key in ("request_id", "content", "input_kind")}).model_dump()


def public_task_run(run: Dict[str, Any]) -> Dict[str, Any]:
    attempts = run.get("attempts") if isinstance(run.get("attempts"), list) else []
    metadata = run.get("metadata") or {}
    return {
        "run_id": str(run.get("run_id") or ""),
        "run_type": str(run.get("run_type") or "workflow"),
        "status": str(run.get("status") or "unknown"),
        "session_id": str(run.get("session_id") or "") or None,
        "trace_id": str(run.get("trace_id") or "") or None,
        "attempt_count": len(attempts),
        "started_at": run.get("started_at"),
        "updated_at": run.get("updated_at"),
        "ended_at": run.get("ended_at"),
        "input_request": metadata.get("input_request") if run.get("status") == "waiting_user" else None,
        "output": metadata.get("output") if run.get("run_type") == "conversation_task" else None,
        "pending_confirmation": public_pending_confirmation(metadata.get("pending_action"))
        if run.get("run_type") == "conversation_task" and run.get("status") == "waiting_human" else None,
    }


def public_task(task: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(task, dict):
        return None
    progress = GoalGapState.model_validate(task.get("goal_gaps") or {})
    return {
        "task_id": str(task.get("task_id") or ""),
        "title": str(task.get("title") or "Untitled task"),
        "objective": str(task.get("objective") or ""),
        "status": str(task.get("status") or "open"),
        "revision": max(0, int(task.get("revision") or 0)),
        "session_ids": [str(value) for value in task.get("session_ids") or [] if value],
        "source": str(task.get("source") or "user"),
        "runs": [public_task_run(run) for run in task.get("runs") or [] if isinstance(run, dict)],
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "completed_at": task.get("completed_at"),
        "goal_gaps": GoalGapView.model_validate(task["goal_gaps"]).model_dump() if task.get("goal_gaps") else None,
        "goal_progress": {"revision": progress.revision, **gap_outcome(progress)},
    }


def public_tasks(tasks: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [row for task in tasks if (row := public_task(task)) is not None]


def public_workflow_run(run: Dict[str, Any]) -> Dict[str, Any]:
    current = run.get("current_step") if isinstance(run.get("current_step"), dict) else None
    return {
        "workflow_run_id": str(run.get("workflow_run_id") or run.get("run_id") or ""),
        "workflow_id": str(run.get("workflow_id") or ""),
        "session_id": str(run.get("session_id") or "") or None,
        "task_id": str(run.get("task_id") or "") or None,
        "status": str(run.get("status") or "unknown"),
        "current_step_id": str(run.get("current_step_id") or "") or None,
        "current_step": (
            {
                "step_id": str(current.get("step_id") or ""),
                "name": str(current.get("name") or ""),
                "step_type": str(current.get("step_type") or ""),
                "status": str(current.get("status") or "unknown"),
                "attempt_count": max(0, int(current.get("attempt_count") or 0)),
            }
            if current
            else None
        ),
        "started_at": run.get("started_at"),
        "updated_at": run.get("updated_at"),
    }


def public_memory_proposal(row: Dict[str, Any]) -> Dict[str, Any]:
    conflicts = row.get("conflict_candidates") if isinstance(row.get("conflict_candidates"), list) else []
    return {
        "proposal_id": str(row.get("proposal_id") or ""),
        "session_id": str(row.get("session_id") or "") or None,
        "status": str(row.get("status") or "pending"),
        "memory_type": str(row.get("memory_type") or ""),
        "target_memory_layer": str(row.get("target_memory_layer") or ""),
        "reason": str(row.get("reason") or ""),
        "conflict_count": len(conflicts),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def public_memory_recall(row: Dict[str, Any]) -> Dict[str, Any]:
    records = row.get("memory_records") if isinstance(row.get("memory_records"), list) else []
    dropped = row.get("dropped_candidates") if isinstance(row.get("dropped_candidates"), list) else []
    return {
        "request_id": str(row.get("request_id") or ""),
        "session_id": str(row.get("session_id") or "") or None,
        "trace_id": str(row.get("trace_id") or "") or None,
        "query_text": str(row.get("query_text") or ""),
        "selected_count": len(records),
        "dropped_count": len(dropped),
    }


def public_workbench(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(snapshot)
    result["task"] = public_task(snapshot.get("task"))
    result["tasks"] = public_tasks(snapshot.get("tasks") or [])
    result["runs"] = [public_task_run(run) for run in snapshot.get("runs") or [] if isinstance(run, dict)]
    result["workflow_runs"] = [public_workflow_run(run) for run in snapshot.get("workflow_runs") or [] if isinstance(run, dict)]
    result["recovery_items"] = [public_workflow_run(run) for run in snapshot.get("recovery_items") or [] if isinstance(run, dict)]
    result["memory_proposals"] = [public_memory_proposal(row) for row in snapshot.get("memory_proposals") or [] if isinstance(row, dict)]
    result["recall_runs"] = [public_memory_recall(row) for row in snapshot.get("recall_runs") or [] if isinstance(row, dict)]
    return result
