# Playbook: How To Add A Tool

This guide explains how to add a locally implemented tool to Promethea so it is discoverable, policy-governed, traceable, and testable.

## Concepts

A tool in Promethea has three parts:

1. `ToolSpec`: metadata, name, description, schema, side-effect level, and permission scope.
2. Implementation: a class with an async `invoke(args, ctx=None)` method.
3. Registration: startup code registers the tool with `ToolService`.

`ToolService` handles policy checks, namespace resolution, event emission, and audit/trace integration. A tool implementation should focus on the capability itself.

## Tool, Extension, And Skill Boundaries

| Type | Use it for | Runtime surface |
| --- | --- | --- |
| Tool | A callable operation the model or workflow can execute. | `ToolService`, `ToolRegistry`, `/api/status/tools` |
| Extension | A plugin or manifest pack that contributes tools, channels, or services. | Extension catalog and plugin runtime |
| Skill | Reusable task instruction plus metadata and optional tool policy hints. | Skill registry and `skill.run` lazy expansion |

If the capability performs an action, implement it as a tool. If the capability is distributed as a drop-in package, wrap it as an extension. If the capability is primarily task guidance or reusable expertise, package it as a skill.

## Capability Provider Runtimes

If a tool represents one stable capability that can be served by multiple backends, keep one public tool id and put provider selection inside the tool's runtime layer.

Use this pattern for official capabilities such as web search:

```text
ToolService
  web.search

WebSearchRuntime
  auto | brave | tavily | serpapi | searxng | duckduckgo
```

Do not register separate official tools for the same general capability, such as `brave.search`, `tavily.search`, and `searxng.search`. That leaks provider choice into router and prompt logic. Provider routing should be explicit runtime configuration, normally stored in `.env` or the current user's `config/users/<user_id>/secrets.env`.

Community tools can stay simple. Add a provider runtime only when the community tool also exposes one stable capability backed by multiple providers.

## Step 1: Define The ToolSpec

```python
from gateway.tools.spec import ToolSpec, ToolSource, SideEffectLevel, CapabilityType

weather_spec = ToolSpec(
    tool_id="weather.current",
    name="weather.current",
    description="Get current weather for a city.",
    source=ToolSource.LOCAL,
    capability_type=CapabilityType.READ_ONLY,
    side_effect_level=SideEffectLevel.NONE,
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
| `NONE` | Read-only; no external state changed. | Allowed by default |
| `WORKSPACE_WRITE` | Writes to user workspace. | Requires explicit allow |
| `EXTERNAL_WRITE` | Modifies an external system. | Requires explicit allow |
| `PRIVILEGED_HOST_ACTION` | Runs host commands or privileged local actions. | Requires explicit allow and audit |

## Step 2: Implement The Tool

```python
from typing import Any, Dict, Optional
from gateway.tool_service import ToolInvocationContext


class WeatherTool:
    tool_id = "weather.current"
    name = "weather.current"
    description = "Get current weather for a city."

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

## Step 3: Register At Startup

Register the tool in application startup code, usually through the same path that initializes official local tools.

```python
from gateway.tool_service import ToolService
from yourmodule.weather_tool import WeatherTool

tool_service = ToolService(event_emitter=event_emitter)
tool_service.register_tool(WeatherTool())
```

`register_tool` adds the tool to both invocation storage and `ToolRegistry`, which is used for policy resolution and catalog queries.

## Step 4: Verify Registration

After starting Promethea:

```bash
curl http://127.0.0.1:8000/api/status/tools
```

The tool should appear with a canonical id such as `weather.current`.

## Step 5: Invoke The Tool

Programmatic gateway invocation:

```python
result = await tool_service.call_tool(
    tool_name="weather.current",
    params={"city": "Tokyo"},
    run_context=run_context,
)
```

Call flow:

1. Namespace and user-boundary checks run.
2. `ToolRegistry.resolve` looks up the spec.
3. `ToolPolicy.evaluate` checks the call against `run_context`.
4. The tool's `invoke` method runs.
5. Tool result events are emitted for trace/audit.

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

- [ ] `ToolSpec` defines correct `side_effect_level` and `capability_type`.
- [ ] `invoke` is async and accepts `(args, ctx=None)`.
- [ ] Tool is registered at startup.
- [ ] Tool appears in `/api/status/tools`.
- [ ] Tests cover main path and error path.
- [ ] Non-read-only tools have explicit policy and audit expectations.

## What You Do Not Need To Change

- `ToolService` invocation logic
- `ToolPolicy` evaluation
- Event emission
- Audit trail capture

These are handled by `ToolService.call_tool`.
