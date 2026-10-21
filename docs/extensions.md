# Extensions

Promethea exposes tools through one user-facing Extension Catalog and one
governed execution path. Package location and transport do not grant privileges:

| Packaging | Backend path | Intended use |
|---|---|---|
| Bundled packages | `agentkit/tools/**/agent-manifest.json` | Included tool implementations, including the `standard` pack. |
| Installed packages | `extensions/community/**/agent-manifest.json` | User, community, or Self Evolve capabilities discovered at runtime. |
| MCP transport | `agent-manifest.json` with `serviceType: "mcp"` | Out-of-process providers connected over standard MCP. |

The Web UI does not need to know which backend path registered the capability.
It reads the unified catalog and shows provider/source badges, tool counts,
callable state, and hot reload controls.

## User-facing APIs

| API | Purpose |
|---|---|
| `GET /api/extensions/catalog` | Return the unified tool package catalog. |
| `POST /api/extensions/reload` | Rescan built-in manifest packs and `extensions/community`, then refresh the runtime tool cache. |
| `GET /api/status/tools` | Low-level callable tool catalog used for diagnostics. |

## Invocation contract

All extension tools are exposed to the model and UI with the same canonical id
shape:

```text
<service_name>.<command_name>
```

For example, a community extension named `my_tool` with command `run` is invoked
as `my_tool.run`. Built-in manifest packs follow the same rule, such as
`computer_control.execute_command`.

Runtime invocation uses the canonical id directly:

```json
{
  "tool_name": "my_tool.run",
  "args": {
    "text": "hello"
  }
}
```

`CapabilityService` resolves the id against the unified `ToolRegistry`; source
and transport are registry metadata rather than model-supplied routing fields.
Older explicit routing fields are accepted only at the input compatibility
boundary. Unknown tools are not treated as successful actions.

## Community extension layout

For native tool classes with `invoke(args, ctx)`, use the factory manifest in
[How To Add A Tool](playbooks/how-to-add-a-tool.md). This is also how the bundled
`standard` package is discovered. The command-service adapter below is useful
when a class already exposes named methods. These are packaging forms, not
separate tool services or permission systems.

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
  "serviceType": "extension_tool",
  "description": "A small custom tool.",
  "entryPoint": {
    "module": "extensions.community.my_tool.service",
    "class": "MyCapabilityService"
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
class MyCapabilityService:
    async def run(self, text: str = ""):
        return {"ok": True, "text": text}
```

Extensions in this folder are scanned at startup. After saving files while the
server is already running, reload from the Web UI or:

```bash
curl -X POST "http://127.0.0.1:8000/api/extensions/reload"
```

Reload stages a complete manifest snapshot first. If validation succeeds, tools
from the selected roots are replaced as one registry update: new commands appear,
changed commands are refreshed, and removed commands are unregistered.

## External MCP providers

External providers use the same manifest discovery lifecycle but declare a
transport instead of a Python `entryPoint`:

```json
{
  "name": "example_mcp",
  "label": "Example MCP",
  "version": "1.0.0",
  "serviceType": "mcp",
  "transport": {
    "type": "stdio",
    "command": "node",
    "args": ["server.js"],
    "env": { "EXAMPLE_TOKEN": "${EXAMPLE_TOKEN}" }
  },
  "capabilities": { "invocation_commands": [] }
}
```

Keep credentials in the process environment or user secrets. Manifest env
values may reference an environment variable with `${NAME}`; secrets should not
be embedded in the manifest.

MCP is a transport adapter below `CapabilityService`, not a second tool system.
Its configuration directory retains provider launch settings; `MCPManager`
discovers remote definitions and maps them into the unified `ToolRegistry`.
Provider names must be unique, and remote tool ids must not collide with another
execution source. Provider configuration reload validates the complete selected
roots before replacement and before closing existing connections. Invalid
configuration leaves the previous configuration intact. Tool-definition refresh
also preserves the previous snapshot on error, but blocks MCP execution until a
valid refresh succeeds; it never silently changes the implementation or risk
classification of an existing in-process tool.

## Agent-generated capabilities

Self Evolve publishes generated versions below
`extensions/community/_generated`. Generated packages use the same catalog and
canonical tool ids as other extensions, but their Python is never imported into
the Gateway process. A trusted runtime proxy executes `tool.py` in a confined
child process and requires one-shot confirmation for every generated command.
Generated code cannot directly read arbitrary host files, open network
connections, or create child processes; those effects remain owned by existing
governed capabilities.

Every generated command declares smoke-test arguments. Validation executes each
command and records a digest of the tested package. Publication rejects later
changes and installs through an atomic directory rename, so a failed publish
does not expose a partial extension. Tasks and published commands are scoped to
their creating user and are omitted from other users' catalogs.

Drafts are mutable only in `.runtime/self-evolve/staging/<task_id>`. Published
versions are append-only: changing an existing capability requires a new
version. Generated runtime data and packages are local artifacts and are
excluded from Git.

## Rules

- Community extensions should be small, explicit, and reversible.
- Do not store API keys, passwords, or personal files in extension folders.
- Sensitive values belong in `.env` or `config/users/<user_id>/secrets.env`.
- Use manifest names and command names that describe the action, not a specific provider implementation.
- Moving a package between bundled and installed roots does not change its tool contract or permissions.

## Included Tool Packages

The `standard` package contributes these domains to the shared catalog:

- `archive`
- `code`
- `cognition`
- `calendar`
- `data`
- `math`
- `mail`
- `memory`
- `organization`
- `runtime`
- `session`
- `skill`
- `text`
- `utility`
- `web`
- `workflow`
- `workspace`

Other manifest packages under `agentkit/tools` appear alongside installed
packages. Every native package is labeled `plugin`; MCP remains a transport
label, not a separate permission tier.
