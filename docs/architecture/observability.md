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

## Audit Coverage (current)

Audit inference currently covers:

- side-effect tool execution attempts/failures
- memory write decision events
- policy-violation-style failures (`blocked`/`deny`/`permission`)
