# ADR-005: Introduce ToolSpec, ToolRegistry, and ToolPolicy

## Status

Accepted

## Date

2026-03-11

## Context

Tool invocation logic existed, but tool metadata, risk classification, and access controls were fragmented across modules and implicit prompt-level behavior.

## Decision

Introduce a standardized tooling governance layer:

- `ToolSpec` as canonical tool contract metadata
- `ToolRegistry` as unified local/MCP registry
- `ToolPolicy` as explicit authorization and side-effect policy
- `ToolService` integrates registry + policy in runtime call path

## Consequences

### Positive

- Tool capabilities and risk are explicit and inspectable.
- Runtime policy has a single enforcement point.
- MCP and local tools can be managed uniformly.

### Trade-offs

- Additional orchestration code in tool service.
- Existing legacy paths still need gradual policy alignment.

## Implementation Mapping

- `gateway/tools/spec.py`
- `gateway/tools/registry.py`
- `gateway/tools/policy.py`
- `gateway/tool_service.py`
- `tests/test_tool_spec_policy_registry.py`
