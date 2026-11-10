from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from gateway.public_contracts import (
    TaskCancelRequest,
    TaskConfirmationRequest,
    TaskControlRequest,
    TaskResumeRequest,
    TaskListResponse,
    TaskResponse,
    TaskRunResponse,
    TaskStartRunRequest,
)
from gateway.public_views import public_task, public_task_run, public_tasks
from ..dispatcher import get_gateway_server
from .auth import get_current_user_id

router = APIRouter(prefix="/tasks", tags=["tasks"])

class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    objective: str = ""
    session_id: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=240)
    objective: Optional[str] = None
    expected_revision: Optional[int] = Field(default=None, ge=1)


def _service():
    service = getattr(get_gateway_server(), "task_service", None)
    if service is None: raise HTTPException(status_code=503, detail="Task service not initialized")
    return service


def _runtime():
    runtime = getattr(get_gateway_server(), "task_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Task runtime not initialized")
    return runtime

@router.post("", response_model=TaskResponse)
async def create_task(payload: TaskCreateRequest, user_id: str = Depends(get_current_user_id)):
    task = _service().create_task(user_id=user_id, title=payload.title, objective=payload.objective, session_id=payload.session_id)
    return {"status": "success", "task": public_task(task)}

@router.get("", response_model=TaskListResponse)
async def list_tasks(status: str = "", limit: int = 100, user_id: str = Depends(get_current_user_id)):
    rows = _service().list_tasks(user_id=user_id, status=status, limit=min(max(1, limit), 200))
    tasks = public_tasks(rows)
    return {"status": "success", "tasks": tasks, "total": len(tasks)}

@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, user_id: str = Depends(get_current_user_id)):
    task = _service().get_task(task_id, user_id=user_id)
    if task is None: raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success", "task": public_task(task)}


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, payload: TaskUpdateRequest, user_id: str = Depends(get_current_user_id)):
    try:
        task = _service().update_task(
            task_id=task_id,
            user_id=user_id,
            title=payload.title,
            objective=payload.objective,
            expected_revision=payload.expected_revision,
        )
        return {"status": "success", "task": public_task(task)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/runs", response_model=TaskRunResponse)
async def start_task_run(task_id: str, payload: TaskStartRunRequest, user_id: str = Depends(get_current_user_id)):
    try:
        run = _runtime().start_workflow(
            task_id=task_id,
            user_id=user_id,
            workflow_id=payload.workflow_id,
            session_id=payload.session_id,
            workspace_id=payload.workspace_id,
            run_context={"task_id": task_id, "source": "task.api"},
            expected_revision=payload.expected_revision,
        )
        run_id = str(run.get("workflow_run_id") or run.get("run_id") or "")
        task = _service().get_task(task_id, user_id=user_id) or {}
        task_run = next((item for item in task.get("runs", []) if str(item.get("run_id") or "") == run_id), None)
        if task_run is None:
            raise RuntimeError(f"started task run was not persisted: {run_id}")
        return {"status": "success", "run": public_task_run(task_run), "detached": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(task_id: str, payload: Optional[TaskControlRequest] = None, user_id: str = Depends(get_current_user_id)):
    try:
        task = _runtime().pause_task(task_id=task_id, user_id=user_id, expected_revision=payload.expected_revision if payload else None)
        return {"status": "success", "task": public_task(task)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(task_id: str, payload: Optional[TaskResumeRequest] = None, user_id: str = Depends(get_current_user_id)):
    try:
        reply = payload.input_reply.model_dump() if payload and payload.input_reply else None
        if reply is None:
            task_state = _runtime().task_service.get_task(task_id, user_id=user_id)
            for run in (task_state or {}).get("runs", []):
                pending = ((run.get("metadata") or {}).get("checkpoint") or {}).get("pending_input") or {}
                if run.get("status") in {"waiting_user", "paused"} and pending.get("input_kind") == "acknowledgement":
                    reply = {"request_id": pending["request_id"], "content": "The authenticated user requested continuation. Verify current state; this does not approve a tool or verify an external result."}
                    break
        task = _runtime().resume_task(task_id=task_id, user_id=user_id, expected_revision=payload.expected_revision if payload else None,
                                      input_reply=reply)
        return {"status": "success", "task": public_task(task)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/confirm", response_model=TaskResponse)
async def confirm_task(task_id: str, payload: TaskConfirmationRequest, user_id: str = Depends(get_current_user_id)):
    driver = getattr(getattr(get_gateway_server(), "conversation_service", None), "conversation_tasks", None)
    if driver is None:
        raise HTTPException(status_code=503, detail="Conversation task driver is unavailable")
    try:
        task = await driver.confirm(user_id, task_id, payload.run_id, payload.tool_call_id, payload.action)
        return {"status": "success", "task": public_task(task)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str, payload: TaskCancelRequest, user_id: str = Depends(get_current_user_id)):
    try:
        task = _runtime().cancel_task(
            task_id=task_id,
            user_id=user_id,
            reason=payload.reason,
            expected_revision=payload.expected_revision,
        )
        return {"status": "success", "task": public_task(task)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
