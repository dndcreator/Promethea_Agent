# Observability Foundation (Backlog 006)

## Goal

Provide a minimal but extensible trace and audit foundation for runtime observability, inspector, and doctor features.

## Schemas

- `TraceEvent`: structured runtime trace envelope
- `AuditEvent`: structured security/policy/decision audit envelope

Implementation:

- `gateway/observability/trace.py`
- `gateway/observability/audit.py`

## Event Bus Integration

`EventEmitter.emit(...)` now records:

1. protocol event history (`EventMessage`)
2. structured trace history (`TraceEvent`)
3. inferred audit history (`AuditEvent`)

Query helpers:

- `get_trace_history(trace_id/session_id/user_id, limit)`
- `get_audit_history(trace_id/session_id/user_id/action, limit)`

## Trace Coverage (current)

Primary runtime chain includes trace fields in major events:

- gateway request received/start/finish
- conversation stage started/finished/failed
- memory recall started/finished
- reasoning started/finished
- tool execution started/finished/failed
- response synthesized
- action state changed and observation committed
- capability snapshot created
- model call recorded

Model-call manifests persist execution identities, referenced snapshot and
Observation ids, prompt-block hashes, request/response hashes, and bounded
model-visible content. Large tool or multimodal values are represented by
hashes and previews. This is sufficient to distinguish missing Runtime context
from a model decision without duplicating arbitrary payloads.

Execution identity is separated across `task_run_id`, `workflow_run_id`,
`conversation_turn_id`, `action_loop_id`, `model_step_id`, `model_call_id`,
`provider_request_id`, `tool_call_id`, and `observation_id`. `model_call_id` is
always Runtime-owned; `provider_request_id` is nullable and is recorded only
when the provider actually returns one. Legacy `run_id` remains readable but
is not used to collapse these levels.

Action state, Observation, model-call, capability-snapshot, and completed
interaction events are committed to the Runtime Event Log before listener
delivery. Failure to persist action-critical facts stops that Runtime path
instead of silently presenting an unaudited success.

The Runtime Event Log is the recovery and audit record, not the application
console. `WorkbenchProjection` folds its stable business identities into the
user-facing activity view. Console output starts at `INFO` even when the file
sink is configured for `DEBUG`, repeated identical access rows are bounded,
and model-provider payload logging remains independently opt-in.

## Audit Coverage (current)

Audit inference currently covers:

- side-effect tool execution attempts/failures
- memory write decision events
- policy-violation-style failures (`blocked`/`deny`/`permission`)
