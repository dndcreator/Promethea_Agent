# Workspace Model (Backlog 009)

## Goal

Provide a controlled workspace sandbox for agent artifacts.

## Core Objects

- `WorkspaceHandle`
  - `workspace_id`
  - `user_id`
  - `root_path`
  - `permissions`
  - `metadata`

Implementation:

- `gateway/workspace_service.py`

## Sandbox Policy (v1)

- all reads/writes are resolved under workspace root
- path traversal outside root is blocked
- write requires workspace permission (`permissions.write=true`)

## Artifact Store (v1)

- `create_document`
- `update_document`
- `list_artifacts`
- `snapshot_artifact`

Supported first-class artifacts:

- markdown/text documents
- json-like output files
- run output snapshots

## Runtime Integration

- `GatewayServer` resolves a workspace handle into `RunContext.workspace_handle`
- successful chat responses can be persisted as workspace markdown artifacts
- workspace writes emit events for trace/audit

Events:

- `workspace.artifact.written`
- `workspace.write.blocked`

## Canvas Applications

The Canvas shell hosts workspace-owned applications without changing the main
chat UI or Agent Core. `EnvironmentController` owns environment identity and
app-state revisions; `CapabilityService` remains the execution boundary. The
TypeScript SDK provides authenticated state/lifecycle requests and a restricted
MessageChannel bridge for opaque-origin frames, not a second tool executor.

Self Evolve builds and verifies applications before deploying them. Session
applications remain conversation-scoped; retained copies live in the user's
`_canvas_library` workspace and enter personal workspace archives with their
static files and app data. Running processes and credentials are never restored.

See [Self Evolve](../../agentkit/tools/self_evolve/README.md) for authoring,
verification, repair, and browser requirements.

Simple applications may use schema-validated component documents rather than
model-written page code. Both paths produce verified artifacts in the same
Canvas lifecycle. See [Intelligent Canvas](./intelligent-canvas.md) for the
implemented grammar, security boundaries, and persistence contract.

