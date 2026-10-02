"""Stable, transport-neutral contracts exposed to external clients.

These models describe the public runtime boundary. They deliberately avoid
Python service objects such as RunContext, executors, stores, and model clients.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Type
from uuid import uuid4

from pydantic import BaseModel, Field


PUBLIC_CONTRACT_VERSION = "1.0"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublicContract(BaseModel):
    """Common configuration for additive public contracts."""

    model_config = {"extra": "ignore"}


class Error(PublicContract):
    code: str
    message: str
    retryable: bool = False
    trace_id: Optional[str] = None
    dependency: Optional[str] = None
    advice: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class Attachment(PublicContract):
    file_id: Optional[str] = None
    filename: Optional[str] = None
    modality: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None
    text_extraction_status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserFile(PublicContract):
    file_id: str
    filename: str
    bytes: int = 0
    content_type: str = ""
    uploaded_at: Optional[float] = None
    session_id: Optional[str] = None
    text_chars: int = 0
    modality: str = "document"
    text_extraction_status: str = "empty_or_unsupported"


class FileUploadResponse(PublicContract):
    status: str = "success"
    file: UserFile


class CanvasEnvironment(PublicContract):
    environment_id: str
    name: str
    kind: Literal["static", "process"] = "static"
    workspace_id: str
    root: str = "."
    entrypoint: str = "index.html"
    status: Literal["ready", "running", "stopped", "interrupted", "failed"] = "ready"
    port: Optional[int] = None
    pid: Optional[int] = None
    revision: int = 1
    last_command_digest: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    preview_url: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CanvasEnvironmentList(PublicContract):
    workspace_id: str
    environments: List[CanvasEnvironment] = Field(default_factory=list)


class RunRequest(PublicContract):
    message: str
    session_id: Optional[str] = None
    stream: bool = False
    requested_mode: Optional[str] = None
    requested_skill: Optional[str] = None
    requested_workflow: Optional[str] = None
    attachments: List[Attachment] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(PublicContract):
    tool_call_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "pending", "needs_confirmation", "running", "completed", "failed"
    ] = "pending"


class ToolResult(PublicContract):
    tool_call_id: str
    tool_name: str
    status: Literal["completed", "failed"]
    result: Any = None
    error: Optional[Error] = None


class RunResponse(PublicContract):
    response: str = ""
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    status: str = "success"
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    memory_write_summary: Optional[Dict[str, Any]] = None
    error: Optional[Error] = None


class Session(PublicContract):
    session_id: str
    title: str = "New Chat"
    created_at: Optional[float] = None
    last_activity: Optional[float] = None
    message_count: int = 0
    pinned: bool = False


class Event(PublicContract):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    event_type: str
    occurred_at: datetime = Field(default_factory=_utc_now)
    seq: Optional[int] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    source: str = "gateway"
    payload: Dict[str, Any] = Field(default_factory=dict)


class TaskRun(PublicContract):
    run_id: str
    run_type: str = "workflow"
    status: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    attempt_count: int = 0
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    ended_at: Optional[str] = None


class Task(PublicContract):
    task_id: str
    title: str
    objective: str = ""
    status: str
    revision: int
    session_ids: List[str] = Field(default_factory=list)
    source: str = "user"
    runs: List[TaskRun] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class TaskControlRequest(PublicContract):
    expected_revision: Optional[int] = Field(default=None, ge=1)


class TaskStartRunRequest(TaskControlRequest):
    workflow_id: str
    session_id: str = "default_session"
    workspace_id: Optional[str] = None


class TaskCancelRequest(TaskControlRequest):
    reason: str = "user_cancelled"


class TaskResponse(PublicContract):
    status: str = "success"
    task: Task


class TaskListResponse(PublicContract):
    status: str = "success"
    tasks: List[Task] = Field(default_factory=list)
    total: int = 0


class TaskRunResponse(PublicContract):
    status: str = "success"
    run: TaskRun
    detached: bool = True


class WorkbenchScope(PublicContract):
    user_id: str
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None


class WorkbenchActivity(PublicContract):
    activity_id: str
    event_id: Optional[str] = None
    seq: int = 0
    occurred_at: Optional[str] = None
    event_type: str
    kind: str
    subject: str
    summary: str = ""
    status: str
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    detail: Dict[str, Any] = Field(default_factory=dict)


class WorkbenchWaitingAction(PublicContract):
    kind: str
    id: Optional[str] = None
    task_id: Optional[str] = None
    status: Optional[str] = None


class WorkflowStepSummary(PublicContract):
    step_id: str
    name: str = ""
    step_type: str = ""
    status: str = "unknown"
    attempt_count: int = 0


class WorkflowRunSummary(PublicContract):
    workflow_run_id: str
    workflow_id: str
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    status: str
    current_step_id: Optional[str] = None
    current_step: Optional[WorkflowStepSummary] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None


class MemoryWriteProposalSummary(PublicContract):
    proposal_id: str
    session_id: Optional[str] = None
    status: str
    memory_type: str = ""
    target_memory_layer: str = ""
    reason: str = ""
    conflict_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MemoryRecallSummary(PublicContract):
    request_id: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    query_text: str = ""
    selected_count: int = 0
    dropped_count: int = 0


class CognitionItem(PublicContract):
    cognition_id: str
    content: str
    domain: Literal["self", "user", "projects", "world", "active"] = "world"
    state: Literal["current", "evolving", "uncertain", "historical"] = "current"
    kind: str = "memory"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    updated_at: Optional[Any] = None
    memory_id: Optional[str] = None
    proposal_id: Optional[str] = None
    source_layer: str = ""
    related: List[str] = Field(default_factory=list)
    action_required: bool = False


class CognitionBundle(PublicContract):
    version: str = "self_model.cognition.v1"
    model_scope: str = "self_model.cognition"
    user_id: str
    generated_at: Optional[str] = None
    items: List[CognitionItem] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class CognitionResponse(PublicContract):
    status: str = "success"
    user_id: str
    cognition: CognitionBundle


class WorkbenchSnapshot(PublicContract):
    version: str = "workbench.v1"
    scope: WorkbenchScope
    task: Optional[Task] = None
    tasks: List[Task] = Field(default_factory=list)
    runs: List[TaskRun] = Field(default_factory=list)
    workflow_runs: List[WorkflowRunSummary] = Field(default_factory=list)
    timeline: List[WorkbenchActivity] = Field(default_factory=list)
    current_activity: Optional[WorkbenchActivity] = None
    artifacts: List[WorkbenchActivity] = Field(default_factory=list)
    waiting_actions: List[WorkbenchWaitingAction] = Field(default_factory=list)
    memory_proposals: List[MemoryWriteProposalSummary] = Field(default_factory=list)
    recall_runs: List[MemoryRecallSummary] = Field(default_factory=list)
    recovery_items: List[WorkflowRunSummary] = Field(default_factory=list)
    active_runtime_runs: List[str] = Field(default_factory=list)
    cursor: int = 0


PUBLIC_CONTRACT_MODELS: Dict[str, Type[BaseModel]] = {
    model.__name__: model
    for model in (
        Error,
        Attachment,
        UserFile,
        FileUploadResponse,
        CanvasEnvironment,
        CanvasEnvironmentList,
        RunRequest,
        RunResponse,
        Session,
        Event,
        ToolCall,
        ToolResult,
        TaskRun,
        Task,
        TaskControlRequest,
        TaskStartRunRequest,
        TaskCancelRequest,
        TaskResponse,
        TaskListResponse,
        TaskRunResponse,
        WorkbenchScope,
        WorkbenchActivity,
        WorkbenchWaitingAction,
        WorkflowStepSummary,
        WorkflowRunSummary,
        MemoryWriteProposalSummary,
        MemoryRecallSummary,
        CognitionItem,
        CognitionBundle,
        CognitionResponse,
        WorkbenchSnapshot,
    )
}


def build_public_contract_schema() -> Dict[str, Any]:
    """Build one deterministic JSON Schema bundle for non-HTTP transports."""

    definitions: Dict[str, Any] = {}
    for name, model in PUBLIC_CONTRACT_MODELS.items():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        definitions.update(schema.pop("$defs", {}))
        definitions[name] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://promethea.local/contracts/runtime-v1.schema.json",
        "title": "Promethea Runtime Public Contracts",
        "version": PUBLIC_CONTRACT_VERSION,
        "$defs": definitions,
    }
