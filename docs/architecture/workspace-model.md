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

## Sandbox Policy (MVP)

- all reads/writes are resolved under workspace root
- path traversal outside root is blocked
- write requires workspace permission (`permissions.write=true`)

## Artifact Store (MVP)

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

## Extension Path

This MVP is designed for follow-up integration with:

- canvas/desktop artifact editing
- workflow output routing
- richer workspace permissions and versioning
