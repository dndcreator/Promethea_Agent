# ADR-008: Reasoning Node State Machine

## Status

Accepted

## Date

2026-03-12

## Context

Reasoning nodes previously used ad-hoc status values and lacked explicit transition rules. This made recovery, workflow integration, and replay behavior hard to reason about.

## Decision

Introduce a unified node state machine and integrate it into `ReasoningService` main execution path.

### State Model

- `pending`
- `running`
- `waiting_tool`
- `waiting_human`
- `succeeded`
- `failed`
- `skipped`

### Transition Control

- Transition rules are centralized in `gateway/reasoning_state_machine.py`.
- Runtime transitions are enforced via `_transition_node_status(...)` in `ReasoningService`.

### Node Contract Extension

`ReasoningNode` now includes:

- evidence/result payloads
- tool and verifier context
- human-gate metadata
- checkpoint snapshot data

## Consequences

### Positive

- Reasoning execution becomes explicitly stateful and recoverable.
- Tool/human/verifier interaction points are represented in node state.
- Workflow/replay layers can reuse stable node-state contracts.

### Trade-offs

- Slightly higher implementation complexity for step orchestration.
- Conservative waiting-human fallback still needs full productized human-review queue.

## Implementation Mapping

- `gateway/reasoning_state_machine.py`
- `gateway/reasoning_service.py`
- `tests/test_reasoning_node_state_machine.py`
- `docs/architecture/reasoning-model.md`
