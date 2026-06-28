# Extensions

Promethea exposes tools through one user-facing Extension Catalog while keeping
two backend registration paths:

| Provider | Backend path | Intended use |
|---|---|---|
| `official` | `gateway/official_tools/*.py` and built-in `agentkit/tools/**/agent-manifest.json` | Release-grade built-in capabilities. |
| `community` | `extensions/community/**/agent-manifest.json` | User or community extensions dropped into the backend folder. |

The Web UI does not need to know which backend path registered the capability.
It reads the unified catalog and shows provider/source badges, tool counts,
callable state, and hot reload controls.

## User-facing APIs

| API | Purpose |
|---|---|
| `GET /api/extensions/catalog` | Return unified official/community extension catalog. |
| `POST /api/extensions/reload` | Rescan built-in manifest packs and `extensions/community`, then refresh the runtime tool cache. |
| `GET /api/status/tools` | Low-level callable tool catalog used for diagnostics. |
| `GET /api/status/tools/official` | Official local-tool subset. |

## Invocation contract

All extension tools are exposed to the model and UI with the same canonical id
shape:

```text
<service_name>.<command_name>
```

For example, a community extension named `my_tool` with command `run` is invoked
as `my_tool.run`. Built-in MCP manifest packs follow the same rule, such as
`computer_control.execute_command`.

Runtime invocation still carries structured fields:

```json
{
  "tool_name": "my_tool.run",
  "agentType": "mcp",
  "service_name": "my_tool",
  "args": {
    "tool_name": "run",
    "text": "hello"
  }
}
```

Before execution, `ToolService` normalizes the call against the unified
`ToolRegistry`. Common JSON mistakes are tolerated only when they can be mapped
to a registered manifest command. Unknown tools are not treated as successful
actions.

## Community extension layout

Drop a folder under `extensions/community`:

```text
extensions/community/my_tool/
  agent-manifest.json
  service.py
```

Minimal manifest:

```json
{
  "name": "my_tool",
  "label": "My Tool",
  "version": "0.1.0",
  "serviceType": "mcp",
  "description": "A small custom tool.",
  "entryPoint": {
    "module": "extensions.community.my_tool.service",
    "class": "MyToolService"
  },
  "capabilities": {
    "invocation_commands": [
      {
        "command": "run",
        "description": "Run the custom action."
      }
    ]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "text": { "type": "string" }
    }
  }
}
```

Service class:

```python
class MyToolService:
    async def run(self, text: str = ""):
        return {"ok": True, "text": text}
```

Extensions in this folder are scanned at startup. After saving files while the
server is already running, reload from the Web UI or:

```bash
curl -X POST "http://127.0.0.1:8000/api/extensions/reload"
```

## Rules

- Community extensions should be small, explicit, and reversible.
- Do not store API keys, passwords, or personal files in extension folders.
- Sensitive values belong in `.env` or `config/users/<user_id>/secrets.env`.
- Use manifest names and command names that describe the action, not a specific provider implementation.
- The same capability can later move from community to official without changing the UI catalog contract.

## Release official extension set

The current built-in extension surface covers:

- `archive`
- `code`
- `data`
- `math`
- `memory`
- `runtime`
- `session`
- `skill`
- `text`
- `utility`
- `web`
- `workflow`
- `workspace`

Built-in manifest packs under `agentkit/tools` also appear as official
extensions when their manifests are loaded.
