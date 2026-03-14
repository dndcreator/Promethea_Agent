# Reasoning Model (Backlog 008)

## Goal

Introduce a recoverable, explicit state machine for reasoning nodes.

## Node State Machine

States:

- `pending`
- `running`
- `waiting_tool`
- `waiting_human`
- `succeeded`
- `failed`
- `skipped`

Allowed transitions (baseline):

- `pending -> running | skipped | failed`
- `running -> waiting_tool | waiting_human | succeeded | failed | skipped`
- `waiting_tool -> running | failed`
- `waiting_human -> running | failed | skipped`

Terminal states:

- `succeeded`
- `failed`
- `skipped`

## ReasoningNode Contract

`ReasoningNode` now carries state-machine and recovery fields:

- `status`
- `evidence`
- `result`
- `tool_calls`
- `human_gate`
- `verifier_state`
- `checkpoint`

## Runtime Integration

`ReasoningService` main step execution path now uses explicit transitions:

- `pending -> running` when step starts
- `running -> waiting_tool -> running` around tool calls
- optional `running -> waiting_human` when tool verification is uncertain
- `running -> succeeded` when step completes
- transition to `failed` on execution errors

## Recovery Primitives

Service-level helpers support recovery/resume:

- `_transition_node_status(...)`
- `_resume_node_from_waiting_tool(...)`
- `_resume_node_from_waiting_human(...)`
- `_snapshot_node(...)`

These primitives are designed to be reused by workflow engine and replay tooling.
