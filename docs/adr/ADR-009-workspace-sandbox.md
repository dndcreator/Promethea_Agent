# ADR-009: Workspace Sandbox MVP

## Status

Accepted

## Date

2026-03-12

## Context

Agent outputs increasingly include structured artifacts (plans, notes, evidence, workflow outputs). Without a bounded workspace, file writes are difficult to govern and audit.

## Decision

Introduce a workspace sandbox MVP with explicit handle + path policy + artifact operations.

### Workspace Handle

A `WorkspaceHandle` carries workspace identity, owner, root path, permissions, and metadata.

### Sandbox Rules

- deny path escape outside workspace root
- deny write when workspace is read-only
- all write operations emit traceable events

### Artifact Operations

- create/update document
- list artifacts
- snapshot artifact

### Runtime Hook

Gateway chat success path can persist assistant output into workspace artifact files, tied to run trace fields.

## Consequences

### Positive

- agent outputs become managed artifacts rather than transient text only
- workspace boundary provides safety baseline for future tools/workflows
- trace/audit visibility exists for write and blocked-write events

### Trade-offs

- MVP is file-based and intentionally minimal
- no full multi-user collaborative version control yet

## Implementation Mapping

- `gateway/workspace_service.py`
- `gateway/server.py`
- `gateway/protocol.py`
- `gateway/observability/audit.py`
- `tests/test_workspace_sandbox.py`
- `docs/architecture/workspace-model.md`
