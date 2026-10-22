"""Workflow definition normalization, validation and dependency selection."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .workflow_models import (
    STEP_STATUS_PENDING, STEP_STATUS_RUNNING, STEP_STATUS_SKIPPED, STEP_STATUS_SUCCEEDED,
    WorkflowDefinition, WorkflowError, WorkflowStep,
)


def normalize_definition(definition: WorkflowDefinition) -> None:
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


def validate_definition(definition: WorkflowDefinition) -> None:
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
        _ensure_acyclic_definition(definition)


def _ensure_acyclic_definition(definition: WorkflowDefinition) -> None:
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


def scheduler_mode_for_type(workflow_type: str) -> str:
    wft = str(workflow_type or "linear").strip().lower()
    if wft == "linear":
        return "sequential"
    if wft == "parallel":
        return "dependency_batch"
    if wft in {"dag", "graph"}:
        return "dependency_graph"
    return "unknown"


def dependencies_satisfied(step: WorkflowStep, all_steps: List[WorkflowStep]) -> bool:
    if not step.depends_on:
        return True
    status_by_id = {s.step_id: s.status for s in all_steps}
    for dep in step.depends_on:
        if status_by_id.get(dep) not in {STEP_STATUS_SUCCEEDED, STEP_STATUS_SKIPPED}:
            return False
    return True


def select_next_ready_step_id(steps: List[WorkflowStep], *, workflow_type: str = "linear") -> Optional[str]:
    ready: List[WorkflowStep] = []
    for step in steps:
        if step.status in {STEP_STATUS_PENDING, STEP_STATUS_RUNNING} and dependencies_satisfied(step, steps):
            ready.append(step)
    if not ready:
        return None
    if workflow_type == "linear":
        return ready[0].step_id
    ready_sorted = sorted(ready, key=lambda s: s.step_id)
    return ready_sorted[0].step_id
