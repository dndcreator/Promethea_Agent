# ADR-006: Trace and Audit Foundation

## Status

Accepted

## Date

2026-03-11

## Context

As runtime complexity increases (pipeline stages, tools, memory, reasoning, workflow), basic event logs are insufficient for replay, diagnosis, and security auditing.

## Decision

Introduce a structured observability baseline:

- `TraceEvent` schema for runtime chain visibility
- `AuditEvent` schema for policy/security/decision actions
- event bus integration to persist trace and inferred audit histories
- helper query APIs for inspector/doctor expansion

## Consequences

### Positive

- A single run can be tracked by `trace_id` end-to-end.
- Tool/memory/security-relevant actions become auditable.
- Inspector and doctor have stable data contracts.

### Trade-offs

- Additional in-memory buffering overhead.
- Some legacy paths still require gradual enrichment.

## Implementation Mapping

- `gateway/observability/trace.py`
- `gateway/observability/audit.py`
- `gateway/events.py`
- `tests/test_trace_audit_foundation.py`
