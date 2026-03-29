# Workflow Model (Backlog 012)

## Scope

Workflow Engine provides a resumable workflow runtime with checkpoint support and dependency-aware scheduling.

## Core Objects

- `WorkflowDefinition`
- `WorkflowRun`
- `WorkflowStep`
- `Checkpoint`

## Step Types (v1)

- `reasoning_step`
- `tool_step`
- `memory_step`
- `artifact_step`
- `approval_step`
- `summary_step`

## Engine Contract

`WorkflowEngine` provides:

- `define_workflow(...)`
- `start_workflow(...)`
- `pause_workflow(...)`
- `resume_workflow(...)`
- `retry_step(...)`
- `approve_step(...)`
- `advance_to_next_step(...)`
- `create_checkpoint(...)`

Supported `workflow_type` values:

- `linear`: strictly sequential, one ready step at a time.
- `parallel`: execute all ready steps in a batch.
- `dag`: dependency-graph scheduling (acyclic).
- `graph`: alias of dependency-graph scheduling (acyclic).

Runtime metadata includes `scheduler_mode` to expose effective scheduling behavior (`sequential`, `dependency_batch`, `dependency_graph`).

## Checkpoint Policy

A checkpoint is written after each step completion and on waiting/failed boundaries, capturing:

- run context snapshot (best-effort)
- reasoning state snapshot
- memory summary snapshot
- workspace artifact refs

## Workspace Integration

`artifact_step` writes artifacts via `WorkspaceService` under user/workspace sandbox.

## Human Approval Gate

`approval_step` (or `requires_human_approval=true`) moves run to `waiting_human` until `approve_step` is called.

## Gateway Surface

Protocol methods:

- `workflow.define`
- `workflow.list`
- `workflow.start`
- `workflow.status`
- `workflow.pause`
- `workflow.resume`
- `workflow.retry_step`
- `workflow.approve_step`
- `workflow.checkpoints`

HTTP routes are exposed under `/workflow/*` in gateway HTTP router.

