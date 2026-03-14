from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


WORKFLOW_STATUS_DRAFT = "draft"
WORKFLOW_STATUS_ACTIVE = "active"
WORKFLOW_STATUS_DISABLED = "disabled"

RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_PAUSED = "paused"
RUN_STATUS_WAITING_HUMAN = "waiting_human"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_COMPLETED = "completed"

STEP_STATUS_PENDING = "pending"
STEP_STATUS_RUNNING = "running"
STEP_STATUS_WAITING_HUMAN = "waiting_human"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_SKIPPED = "skipped"
STEP_STATUS_SUCCEEDED = "succeeded"


class WorkflowStep(BaseModel):
    step_id: str
    step_type: str
    name: str
    description: str = ""
    status: str = STEP_STATUS_PENDING
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    requires_human_approval: bool = False
    retry_policy: Dict[str, Any] = Field(default_factory=dict)
    timeout_policy: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    artifact_targets: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    workflow_id: str
    workflow_type: str = "linear"
    name: str
    description: str = ""
    owner_user_id: Optional[str] = None
    agent_id: Optional[str] = None
    skill_id: Optional[str] = None
    steps: List[WorkflowStep] = Field(default_factory=list)
    policy: Dict[str, Any] = Field(default_factory=dict)
    status: str = WORKFLOW_STATUS_ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Checkpoint(BaseModel):
    checkpoint_id: str
    workflow_run_id: str
    step_id: str
    run_context_snapshot: Dict[str, Any] = Field(default_factory=dict)
    reasoning_state_snapshot: Dict[str, Any] = Field(default_factory=dict)
    memory_summary_snapshot: Dict[str, Any] = Field(default_factory=dict)
    workspace_artifact_refs: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowRun(BaseModel):
    workflow_run_id: str
    workflow_id: str
    session_id: str
    user_id: str
    workspace_id: str
    status: str = RUN_STATUS_PENDING
    current_step_id: Optional[str] = None
    checkpoint_id: Optional[str] = None
    steps: List[WorkflowStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
