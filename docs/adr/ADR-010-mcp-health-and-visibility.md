# ADR-010: MCP Health And Tool Visibility Foundation

## Status

Accepted

## Date

2026-03-12

## Context

MCP integration already exists for tool execution, but it lacks stable runtime observability and user-facing inspection data. As the tool ecosystem grows, operators and users need reliable answers to:

- Which MCP services are online/offline/degraded
- What tools each service currently exposes
- What the latest sync/error status is
- Which tools are visible for a specific user context

## Decision

Introduce MCP health snapshots and tool descriptors as first-class runtime contracts.

### Data Contracts

- `MCPServiceHealth`
  - `service_name`, `status`, `last_seen_at`, `last_sync_at`, `tool_count`, `last_error`, `source`, `user_visibility`
- `MCPToolDescriptor`
  - `tool_name`, `service_name`, `description`, `input_schema_summary`, `status`, `enabled`, `last_updated_at`, `user_visibility`

### Gateway Query Endpoints

- `mcp.services.list`
- `mcp.service.health`
- `mcp.service.tools`
- `mcp.tools.visible`

### Runtime Behavior

- manager updates health snapshots on connect/sync/call failure paths
- service health and tool descriptor queries can be used by future Tool Panel/Inspector UIs
- visibility filtering supports service-level user scoping based on manifest visibility hints

## Consequences

### Positive

- MCP capability state becomes inspectable instead of opaque
- panel and diagnostics can use stable backend data contracts
- failures and stale services are easier to detect and triage

### Trade-offs

- visibility policy is currently service-level and minimal
- health data is in-memory and not persisted across process restarts

## Implementation Mapping

- `agentkit/mcp/mcp_manager.py`
- `gateway/protocol.py`
- `gateway/server.py`
- `gateway_integration.py`
- `tests/test_mcp_health_tool_panel.py`
- `docs/architecture/tool-runtime.md`
