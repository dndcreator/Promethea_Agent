# Playbook: How To Add A Tool

This guide explains how to add a locally implemented tool to Promethea so it is discoverable, policy-governed, traceable, and testable.

## Concepts

A tool in Promethea has three parts:

1. `ToolSpec`: metadata, name, description, schema, side-effect level, and permission scope.
2. Implementation: a class with an async `invoke(args, ctx=None)` method.
3. Registration: manifest discovery registers the tool with `CapabilityService`.

`CapabilityService` handles policy checks, namespace resolution, event emission, and audit/trace integration. A tool implementation should focus on the capability itself.

Account- or dependency-backed local tools may expose a synchronous
`check_ready(user_id) -> (bool, reason)` probe. Catalog projection, exact
inspection, and execution authorization use the same probe. Keep it cheap and
local: inspect configuration/dependency availability without network calls or
secret values in the returned reason. Do not equate configuration with remote
service health. The existing manifest `requiresConfig` check remains unchanged.

### Offered Capabilities And Prerequisites

Declare optional `provides` identifiers on a local tool, `ToolSpec`, or manifest
command, for example `provides = ["weather.current"]`. Use up to 16 dotted ASCII
identifiers (letters, digits, underscores and hyphens; at most 160 characters
each). The Registry validates the declaration and projects it through the same
catalog, snapshot and inspection path. An MCP adapter may supply this optional
metadata through its existing registration record; no additional MCP protocol
is required. Tools without it remain discoverable by their canonical tool ID.

Local tools receive the effective invocation's RunContext and configuration in
`ctx.metadata`, set by CapabilityService from its trusted call parameters. Treat
these as internal references; do not serialize configuration into results or
external requests. Tool arguments and preexisting caller metadata cannot replace
the configuration used by Runtime authorization.

`provides` describes an offered operation. `requiresCapability` describes a
Runtime prerequisite, such as browser availability; it is used for readiness,
not as an offered capability. Declare both when both meanings apply. Namespace
matching supports parent/child requests, not free-text inference or a complete
proof that a tool can fulfill an arbitrary goal.

Capability resolution distinguishes an absent declaration from an existing but
unavailable or out-of-scope tool. `task_feasibility: "not_assessed"` means an
unmatched intent is not proof the task is impossible: the Agent can inspect
available groups, compose existing tools or, when enabled, use Self Evolve to
create a reusable implementation. Large candidate schemas are deferred to the
existing `capability_inspect` action. Declarations never grant permission,
credentials, approval or a bypass for an external site's restrictions.

## Tool, Extension, And Skill Boundaries

| Type | Use it for | Runtime surface |
| --- | --- | --- |
| Tool | A callable operation the model or workflow can execute. | `CapabilityService`, `ToolRegistry`, `/api/status/tools` |
| Extension | A plugin or manifest pack that contributes tools, channels, or services. | Extension catalog and plugin runtime |
| Skill | Reusable task instruction plus metadata and optional tool policy hints. | Skill registry and `skill.run` lazy expansion |

If the capability performs an action, implement it as a tool. If the capability is distributed as a drop-in package, wrap it as an extension. If the capability is primarily task guidance or reusable expertise, package it as a skill.

## Persistent Observation Sources

A registered tool can optionally declare `observation_source = True` together
with `side_effect_level = "read_only"`. It still uses the same manifest, Registry,
CapabilityService and policy path; no source-specific service or Agent loop is
needed. The callable schema must accept a JSON-object `cursor`. Return:

```json
{
  "observations": [
    {"key": "document:42", "version": "revision:8", "data": {"state": "updated"}, "references": []}
  ],
  "cursor": {"last_revision": 8}
}
```

Use stable object keys and source versions that distinguish transitions. Do not
use poll timestamps as versions. Results may contain at most 100 unique objects
and 256KB per batch; retain larger evidence at the source and expose a paged read
tool. The Runtime remembers the latest versions for up to 4,096 object keys per
schedule; historical backfill and long-term retention are not unlimited.

Create a schedule with the ordinary `runtime.schedule` tool:

```json
{
  "name": "Observe document updates",
  "service_name": "documents",
  "tool_name": "changes",
  "args": {},
  "interval_seconds": 300,
  "observe": true
}
```

Temporal persists cursor/version changes and an outbox before publishing
`environment.state.changed`. RuntimeEventLog commits the fact before listeners
run; retained idempotency keys make a publication-before-ack crash safe to replay.
Delivery is at least once, not exactly-once arbitrary tool execution. Runtime
assigns the owner and source identity; tools cannot supply another user ID.
Polling identical versions does not publish another change or call a model.
Permission and source declarations are checked again at each collection.

Ambient admits bounded event batches into its existing Task runs and acknowledges
their cursor only after a completed activation. Waiting for approval or stopping
on an execution budget does not consume that batch. SelfModel resolves each
reference from the owner-scoped log; `runtime.read_event` pages retained evidence.
Sources report facts, never whether to repair something or create a task.

This contract does not make plugin code a sandbox: installed implementations
remain trusted host code, and incorrect read-only declarations are not a process
security boundary. Command execution retains the existing approval requirements.

## Capability Provider Runtimes

If a tool represents one stable capability that can be served by multiple backends, keep one public tool id and put provider selection inside the tool's runtime layer.

Use this pattern for capabilities such as web search:

```text
CapabilityService
  web.search

WebSearchRuntime
  auto | brave | tavily | serpapi | searxng | duckduckgo
```

Do not register separate tools for the same general capability, such as `brave.search`, `tavily.search`, and `searxng.search`. That leaks provider choice into router and prompt logic. Provider routing should be explicit runtime configuration, normally stored in `.env` or the current user's `config/users/<user_id>/secrets.env`.

Community tools can stay simple. Add a provider runtime only when the community tool also exposes one stable capability backed by multiple providers.

Provider runtimes remain implementation services below `CapabilityService`. They do
not register additional model-facing tools, and provider selection values must
come from runtime configuration rather than tool-call arguments.

## Step 1: Define The ToolSpec

```python
from gateway.tools.spec import ToolSpec, ToolSource, SideEffectLevel

weather_spec = ToolSpec(
    tool_name="current",
    service_name="weather",
    description="Get current weather for a city.",
    source=ToolSource.LOCAL,
    capability_type="local",
    provides=["weather.current"],
    side_effect_level=SideEffectLevel.READ_ONLY,
    permission_scope="read",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    output_schema={"type": "object"},
    timeout_ms=5000,
)
```

Side-effect levels:

| Level | Meaning | Default policy |
| --- | --- | --- |
| `READ_ONLY` | Read-only; no external state changed. | Allowed by default |
| `WORKSPACE_WRITE` | Writes inside the isolated user workspace. | Allowed unless strict policy blocks it |
| `EXTERNAL_WRITE` | Modifies an external system. | One-shot confirmation |
| `PRIVILEGED_HOST_ACTION` | Runs host commands or controls the host. | One-shot confirmation plus sandbox enforcement |

## Step 2: Implement The Tool

```python
from typing import Any, Dict, Optional
from gateway.capability_service import ToolInvocationContext


class WeatherTool:
    tool_id = "weather.current"
    name = "weather.current"
    description = "Get current weather for a city."
    provides = ["weather.current"]
    side_effect_level = "read_only"
    input_schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": False,
    }
    presentation = {
        "title": "Check weather",
        "title_i18n": {"zh": "查询天气", "en": "Check weather"},
        "subject_arg": "city",
    }

    async def invoke(
        self,
        args: Dict[str, Any],
        ctx: Optional[ToolInvocationContext] = None,
    ) -> Any:
        city = args.get("city", "")
        if not city:
            raise ValueError("city is required")

        return {
            "city": city,
            "temperature_c": 22,
            "conditions": "partly cloudy",
        }
```

`presentation` is optional. It lets the Runtime persist a readable Workbench
card without coupling React to a tool id. Manifest-backed commands accept the
same object, and may also declare typed references such as
`{"kind":"url","arg":"url"}`. Without it, Workbench uses the registered tool
description as a generic title.

Concurrent execution is opt-in: set `concurrency_safe = True` on a local tool,
`concurrencySafe: true` on a discovered manifest command, or `concurrency_safe`
on its trusted Runtime `ToolSpec`. An undeclared tool runs exclusively. Opt in
only if invocations do not race over shared state or a GUI session; read-only
policy classification alone is not a concurrency guarantee. The existing Action
loop enforces the pool limit and ordering barriers, without granting permissions
or automatically retrying side effects. Tool cancellation must release owned
resources and must not report uncertain external effects as a confirmed failure.

The equivalent command declaration in `agent-manifest.json` is:

```json
{
  "command": "current",
  "description": "Get current weather for a city.",
  "presentation": {
    "title": "Check weather",
    "title_i18n": {"zh": "查询天气", "en": "Check weather"},
    "subject_arg": "city"
  }
}
```

Supported fields are `kind`, `title`, `title_i18n`, `subject_arg`, `summary`,
`summary_i18n`, and `references`. Each reference declares a generic `kind` and
either an argument name in `arg` or a fixed `target`. Invalid declarations fail
registration instead of silently producing a broken card.

## Step 3: Package For Discovery

Add `extensions/community/weather/agent-manifest.json`:

```json
{
  "name": "weather",
  "label": "Weather",
  "version": "0.1.0",
  "serviceType": "tool",
  "entryPoint": {
    "module": "extensions.community.weather.tools",
    "factory": "create_tools"
  }
}
```

In `extensions/community/weather/tools.py`, define the tool above and its factory:

```python
def create_tools(runtime):
    return [WeatherTool()]
```

Both `agentkit/tools` and `extensions/community` use this discovery path. Startup
scans manifests; `/api/extensions/reload` refreshes implementations and removes
deleted tools. Factories return fresh instances on each load, never register them themselves. Native
tool schemas, readiness probes and presentation hooks remain on the tool class;
they do not need to be copied into JSON. Existing `{module, class}` command
manifests and external MCP transport manifests are also supported by the same
catalog and governed execution path.

The factory receives trusted host bindings (`workspace_service`, `memory_service`,
`message_manager`, `gateway_server`, and available Runtime services). Use only the
dependencies needed by the package; return no dependent tools when a service is
absent. Bindings never come from model arguments and confer no approval. Package
code is operator-installed Python code, not sandboxed by importing it. Install
only trusted packages; Agent-generated tools must use Self Evolve's existing
sandboxed proxy, and out-of-process providers should use MCP.

`ToolSpec` is derived from the registered instance. The explicit spec above
illustrates the Runtime contract; there is no second spec file to maintain.

For an MCP command whose risk depends on one parameter, declare the mapping in
its manifest instead of adding tool-name branches to policy code:

```json
{
  "command": "screen_action",
  "sideEffectLevel": "privileged_host_action",
  "sideEffectSelector": {
    "parameter": "action",
    "default": "privileged_host_action",
    "groups": {
      "read_only": ["screenshot", "get_screen_size"]
    }
  }
}
```

Unknown values use `default`, so newly added actions fail toward the declared
safe boundary until their metadata is reviewed.

## Step 4: Verify Registration

After starting Promethea:

```bash
curl http://127.0.0.1:8000/api/status/tools
```

The tool should appear with a canonical id such as `weather.current`.

## Step 5: Invoke The Tool

Programmatic gateway invocation:

```python
result = await capability_service.call_tool(
    tool_name="weather.current",
    params={"city": "Tokyo"},
    run_context=run_context,
)
```

Call flow:

1. Namespace and user-boundary checks run.
2. `ToolRegistry.resolve_for_call` applies any manifest-declared action effect.
3. `ToolPolicy.evaluate` checks the call against `run_context`.
4. If policy requires confirmation, CapabilityService requires an active Runtime grant for the exact call before hooks or `invoke`. Otherwise it raises `TOOL_CONFIRMATION_REQUIRED`; direct calls and missing `RunContext` are not exemptions.
5. The tool's `invoke` method runs.
6. Tool result events are emitted for trace/audit.

Do not accept `approved` arguments as authorization or mint an `approval_scope`
inside a tool. User-facing confirmation is owned by Runtime. Nested high-risk
calls need their own exact grant; workflow-step approval and permission allowlists
are not substitutes for tool-call confirmation.

## Step 6: Add Tests

```python
import pytest
from yourmodule.weather_tool import WeatherTool


@pytest.mark.asyncio
async def test_weather_tool_returns_conditions():
    tool = WeatherTool()
    result = await tool.invoke({"city": "Tokyo"})
    assert result["city"] == "Tokyo"
    assert "temperature_c" in result


@pytest.mark.asyncio
async def test_weather_tool_requires_city():
    tool = WeatherTool()
    with pytest.raises(ValueError, match="city is required"):
        await tool.invoke({})
```

## Checklist

- [ ] The registration or MCP manifest defines the correct side-effect metadata.
- [ ] `invoke` is async and accepts `(args, ctx=None)`.
- [ ] Tool is registered at startup.
- [ ] Tool appears in `/api/status/tools`.
- [ ] Tests cover main path and error path.
- [ ] Non-read-only tools have explicit policy and audit expectations.

## What You Do Not Need To Change

- `CapabilityService` invocation logic
- `ToolPolicy` evaluation
- Event emission
- Audit trail capture

These are handled by `CapabilityService.call_tool`.
