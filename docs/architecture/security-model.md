# Security Model

## 1. Namespace Layers

Promethea runtime enforces four namespace layers:

- `config namespace`: user-scoped runtime config and policy sections
- `session namespace`: `SessionState` ownership and chat/session binding
- `memory namespace`: recall/write decisions scoped by `user_id`
- `workspace namespace`: sandbox root path bound to a single user/workspace pair

## 2. Boundary Principles

- All runtime core objects carry explicit `user_id` ownership.
- Cross-user access is denied by default.
- Side-effect tools require explicit policy allow and can be audited.
- Sensitive secret paths are isolated and should emit security audit events.

## 3. Runtime Enforcement Points

- `gateway/memory_service.py`: drops cross-user recall candidates and emits `security.boundary.violation`
- `gateway/workspace_service.py`: blocks cross-user workspace access through owner assertion
- `gateway/tool_service.py`: blocks mismatched `RunContext.user_id` and invocation identity
- `gateway/http/routes/config.py`: rejects cross-user config access in HTTP layer
- `gateway/server.py`: workflow ownership checks and workspace access guard

## 4. Security Audit Baseline

Security audit uses event-bus derived audit events:

- source: `gateway/events.py` + `gateway/observability/audit.py`
- query/report: `gateway/security/audit.py`
- HTTP endpoints:
  - `GET /api/security/audit/report`
  - `GET /api/security/audit/events`

The report summarizes:

- namespace violation attempts
- side-effect tool executions
- workspace blocked events
- secret access events
