# ADR-016 Namespace And Security Audit Foundation

- Status: Accepted
- Date: 2026-03-13
- Backlog: 016-namespace-and-security-audit

## Context

Runtime already had partial user-boundary checks, but lacked a unified namespace violation audit path and a stable security report entry.

## Decision

We introduce a minimum enforceable security baseline:

1. Keep four namespace layers as first-class runtime concepts: config/session/memory/workspace.
2. Add explicit boundary enforcement in memory/workspace/tool key paths.
3. Add canonical security events:
   - `security.boundary.violation`
   - `security.secret.access`
4. Extend audit inference to map those events into structured `AuditEvent` records.
5. Add a report/query module and HTTP endpoints:
   - `gateway/security/audit.py`
   - `GET /api/security/audit/report`
   - `GET /api/security/audit/events`

## Consequences

- Multi-user isolation becomes auditable and queryable.
- Cross-user attempts in critical paths are no longer silent drops.
- Future doctor/audit tooling can build on stable audit actions.
- Scope remains intentionally minimal; not a full RBAC/ABAC system.
