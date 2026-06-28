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
- `normalize_call(tool_name, params)` maps model-produced calls to a canonical registered tool id
- `resolve(tool_name, params)` returns canonical `ToolSpec`

Canonical ids use these forms:

- official local tools: `<category>.<tool>`, for example `web.search`
- MCP/community tools: `<service>.<action>`, for example `computer_control.execute_command`

The normalizer is registry-driven. If the model swaps `service_name` and
`tool_name`, omits the full id, or marks an MCP tool as `local`, the runtime
only corrects the call when the resulting `<service>.<action>` exists in the
registered specs. This avoids hardcoded per-tool aliases while still making
tool calls tolerant of common LLM JSON mistakes.

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

1. registry synchronization from local official tools and MCP manifests
2. registry-driven call normalization
3. registry resolution
4. policy evaluation (runtime path with `RunContext`)
5. tool invocation

Policy/debug context is attached into tool lifecycle events.

## Lightweight ReAct For Action Turns

Promethea does not start the full ToT/reasoning tree for every request. Pure
chat stays on the direct path. When the prompt policy routes a turn to
`light_action`, the runtime uses the existing tool-call loop as a lightweight
ReAct path:

```text
Action -> runtime Observation -> minimal verification/correction -> Answer
```

The verification step is intentionally small. The model is instructed to verify
state-changing or externally verifiable claims only when a cheap check is
available, such as file existence, readback, status, source/date, or command
result checks. If a tool fails or the observation does not prove completion, the
final answer must report failure or uncertainty instead of claiming success.

`light_action` keeps a small action budget by default: one primary action, one
optional verification/correction, and one recovery step for normal
external-source failures. `deep_reasoning` and `workflow` still use the heavier
reasoning/tree machinery.

## Action Service Boundary

`ActionService` is the gateway first-class service for action-mode execution.
It is not a global router and it does not own memory writes. `ConversationService`
and `PromptPolicyRouter` decide whether a turn needs action; `ActionService`
then owns the action run lifecycle:

- create an action run and trace
- delegate action execution to the existing lightweight ReAct/tool-call loop
- keep executable calls inside the existing tool runtime
- track budget/status and return a structured action result

Memory recall and memory writes remain owned by `ConversationService` and
`MemoryService`. Durable workflow/checkpoint behavior remains owned by
MoIRAI/Workflow services. Action runs only expose structured traces that those
services may consume later.

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
