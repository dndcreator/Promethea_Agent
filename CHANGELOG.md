# Changelog

All notable changes to Promethea are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning: [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- `README.md` rewrite with feature table, architecture diagram, quickstart, and comparison table
- `example.env` with cloud / local / Azure model configuration examples
- `CONTRIBUTING.md` with PR checklist and Definition of Done
- `docs/configuration.md` — full configuration reference
- `docs/quickstart-local-model.md` — local model setup guide
- `docs/scenario-workflow-audit.md` — end-to-end workflow + workspace + audit demo

---

## [0.1.0] — 2026-03

### Gateway & Protocol (Backlog 001–002)
- Unified `RunContext` and `SessionState` objects
- `GatewayRequest` / `GatewayResponse` / `GatewayEvent` protocol contracts
- Event bus (`EventEmitter`) with bounded trace and audit history

### Conversation Pipeline (Backlog 003)
- Six-stage pipeline: Input Normalization → Mode Detection → Memory Recall → Planning → Tool Execution → Response Synthesis
- `ConversationPipeline` staging with per-stage structured outputs

### Prompt Assembly (Backlog 004)
- Block-based prompt assembly (`identity`, `policy`, `memory`, `tools`, `workspace`, `reasoning`, `response_format`)
- Token estimation and block compaction support

### Tool Governance (Backlog 005)
- `ToolSpec` with side-effect level, permission scope, timeout hints
- `ToolRegistry` unified across local tools and MCP services
- `ToolPolicy` with allow/deny/mode-aware evaluation

### Observability Foundation (Backlog 006)
- `TraceEvent` and `AuditEvent` structured in-memory history
- `infer_audit_event` — automatic audit inference from trace events

### Memory Write Gate (Backlog 007)
- `MemoryWriteGate` — allow / deny / defer decisions before long-term writes
- Denial reasons: `low_confidence`, `speculative_content`, `short_lived_context`, `conflict_detected`
- `memory.write.decided` event emitted for all write candidates

### Reasoning State Machine (Backlog 008)
- `ReasoningNode` explicit lifecycle states: `pending/running/waiting_tool/waiting_human/succeeded/failed/skipped`
- Transition validation integrated with workflow recovery primitives

### Workspace Sandbox MVP (Backlog 009)
- `WorkspaceService` with user-scoped root path and path-escape protection
- Artifact write, update, list, snapshot operations
- `workspace.artifact.written` and `workspace.write.blocked` audit events

### MCP Health & Tool Panel (Backlog 010)
- `MCPServiceHealth` with status, sync timestamps, last error, user visibility
- `MCPToolDescriptor` for panel/query APIs
- Gateway endpoints: `mcp.services.list`, `mcp.service.health`, `mcp.service.tools`, `mcp.tools.visible`

### Memory Recall Policy & Inspector (Backlog 011)
- `MemoryRecallRequest` / `MemoryRecallResult` structured contracts
- Mode-aware recall policy: `fast / deep / workflow`
- Recall run inspector: selected items, dropped candidates, filter reasons, metrics

### Workflow Engine MVP (Backlog 012)
- `WorkflowDefinition`, `WorkflowRun`, `WorkflowStep`, `Checkpoint` schema
- Step types: `reasoning_step`, `tool_step`, `artifact_step`, `approval_step`, `memory_step`, `summary_step`
- Engine: start / pause / resume / retry / approve / checkpoint
- HTTP routes: `/workflow/*`

### Channel Adapter Framework (Backlog 013)
- Unified adapter interface and metadata model
- Adapter registry with default channels: `web`, `http_api`, `telegram`
- Identity normalization, permission check, request/response mapping per channel

### Skill Layer (Backlog 014)
- `SkillSpec`, `SkillExample`, `SkillEvaluationCase` schema
- Skill registry with official pack loading and user-aware resolution
- `tool_allowlist`, `default_mode`, `system_instruction` injected at runtime
- HTTP: `/api/skills/catalog`, `/api/skills/install`, `/api/skills/activate`

### Config Schema & Migration (Backlog 015)
- `config_version` root marker
- `gateway/config_migrations.py` migration module
- Scoped config access: `get_runtime_config`, `get_user_preferences`, `get_tool_policy_config`

### Namespace & Security Audit (Backlog 016)
- `security.boundary.violation` event type
- `SecurityAuditService.build_report` — per-user audit summary
- HTTP: `GET /api/security/audit/report`, `GET /api/security/audit/events`
- Enforcement in: memory recall, workspace access, tool execution

### Memory Backends
- `FlatMemoryStore` — JSONL backend, zero dependencies
- `SqliteGraphMemoryStore` — SQLite with graph recall via recursive CTE
- MEF (Memory Exchange Format) — lossless export/import across all backends
- `MemoryAdapter.migrate_backend` — live backend cutover and dual-write mode
