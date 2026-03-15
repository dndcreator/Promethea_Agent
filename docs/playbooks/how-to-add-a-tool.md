# Playbook: How to Add a Tool

This guide explains how to add a new locally-implemented tool to Promethea so it is:

- Discoverable via the tool catalog
- Subject to `ToolPolicy` enforcement
- Traced and audited automatically
- Testable in isolation

---

## Concepts

A **tool** in Promethea has three parts:
1. **`ToolSpec`** — metadata: name, description, schema, side-effect level, permission scope
2. **Implementation** — a class with an `invoke` method
3. **Registration** — register with `ToolService` at startup

The `ToolService` handles policy checks and event emission; your tool only needs to implement `invoke`.

---

## Step 1 — Define the ToolSpec

```python
# gateway/tools/spec.py (or your tool's own file)

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

### Side-effect levels

| Level | Meaning | Default policy |
|---|---|---|
| `NONE` | Read-only, no external state changed | Allowed by default |
| `WORKSPACE_WRITE` | Writes to user workspace | Requires explicit allow |
| `EXTERNAL_WRITE` | Modifies external system (API, DB) | Requires explicit allow |
| `PRIVILEGED_HOST_ACTION` | Runs system commands | Requires explicit allow + audit |

For a read-only tool, set `SideEffectLevel.NONE` and it will pass policy checks in all modes.

---

## Step 2 — Implement the tool

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

        # Replace with real implementation
        return {
            "city": city,
            "temperature_c": 22,
            "conditions": "partly cloudy",
        }
```

---

## Step 3 — Register at startup

In `gateway/app.py` or your application startup code:

```python
from gateway.tool_service import ToolService
from yourmodule.weather_tool import WeatherTool

tool_service = ToolService(event_emitter=event_emitter)
tool_service.register_tool(WeatherTool())
```

`register_tool` adds the tool to both `_registered_tools` (for invocation) and `ToolRegistry` (for policy resolution and catalog queries).

---

## Step 4 — Verify registration

After starting Promethea:

```bash
curl http://127.0.0.1:8000/api/tools/list
```

Your tool should appear in the response with `"type": "local"`.

---

## Step 5 — Invoke the tool

Via the gateway server (programmatically):

```python
result = await tool_service.call_tool(
    tool_name="weather.current",
    params={"city": "Tokyo"},
    run_context=run_context,   # carries user_id, trace_id, etc.
)
```

The call flow is:
1. `_assert_tool_namespace` — checks user boundary
2. `ToolRegistry.resolve` — looks up the spec
3. `ToolPolicy.evaluate` — policy check against `run_context`
4. `local_tool.invoke(params, ctx)` — your implementation
5. `TOOL_CALL_RESULT` event emitted — captured in trace/audit

---

## Step 6 — Add tests

```python
# tests/test_weather_tool.py
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

---

## Checklist

- [ ] `ToolSpec` defined with correct `side_effect_level` and `capability_type`
- [ ] `invoke` is `async` and accepts `(args, ctx=None)`
- [ ] Tool registered in startup code
- [ ] Appears in `/api/tools/list`
- [ ] Tests cover main path and error path
- [ ] If `side_effect_level` is not `NONE`: tool appears in policy config and is audited

---

## What you do NOT need to change

- `ToolService` invocation logic
- `ToolPolicy` evaluation
- Event emission
- Audit trail capture

These are all handled by `ToolService.call_tool` automatically.
