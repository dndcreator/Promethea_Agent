# Tool Runtime (Backlog 005)

## Goal

Standardize tool governance with unified metadata, registry, and policy enforcement.

## Core Building Blocks

- `ToolSpec` (`gateway/tools/spec.py`)
- `ToolRegistry` (`gateway/tools/registry.py`)
- `ToolPolicy` (`gateway/tools/policy.py`)

## ToolSpec

Each tool is represented with structured metadata:

- input/output schema
- capability type
- side-effect level
- permission scope
- timeout/retry/idempotency hints
- source (`local`, `mcp`, `extension`, `agent`)

## Registry

`ToolRegistry` provides a unified view across local tools and MCP tools.

- local tools are registered via `register_local_tool`
- MCP services/actions are mapped via `register_mcp_services`
- `resolve(tool_name, params)` returns canonical `ToolSpec`

## Policy

`ToolPolicy` enforces:

- allow/deny rules
- mode-specific restrictions
- skill allowlist hooks
- side-effect-safe defaults

Default behavior:

- `read_only` tools can run by default
- side-effect tools (`workspace_write`, `external_write`, `privileged_host_action`) require explicit allow

## Service Integration

`ToolService.call_tool` now uses:

1. registry resolution
2. policy evaluation (runtime path with `RunContext`)
3. tool invocation

Policy/debug context is attached into tool lifecycle events.

## MCP Health And Tool Panel (Backlog 010)

To support a manageable MCP tool panel, runtime now includes MCP-level observability data:

- `MCPServiceHealth`: service status snapshot (`online/offline/degraded`), sync timestamps, last error, and user visibility
- `MCPToolDescriptor`: normalized MCP tool descriptor for panel/query APIs

Gateway exposes MCP query endpoints:

- `mcp.services.list`
- `mcp.service.health`
- `mcp.service.tools`
- `mcp.tools.visible`

This turns MCP from a pure invocation bridge into a diagnosable and inspectable capability source.
