# Extensions

This directory contains Promethea plugin extensions.

## Boundary

| Type | Purpose | Where it lives |
| --- | --- | --- |
| Extension | Drop-in package that registers tools, channels, or services. | `extensions/*`, `extensions/community/*` |
| Tool | Callable action exposed through `ToolService` and policy. | `gateway/official_tools/*`, `agentkit/tools/*`, or an extension |
| Skill | Reusable task instruction and metadata, expanded on demand. | `skills/packs/official/*` |

Extensions can contribute tools or channels, but they are not the same thing as skills. Use a skill for reusable guidance; use an extension when you need to add executable capabilities or integration surfaces.

## Layout

```text
extensions/<plugin_name>/
  promethea.plugin.json
  plugin.py
```

## Built-in Plugins

- `web` (channel)
- `memory` (memory backend integration)
- `feishu` (channel)
- `dingtalk` (channel)
- `wecom` (channel)

## Loading Model

1. Runtime scans `extensions/*`.
2. Manifest is parsed.
3. `plugin.py` registration entry is loaded.
4. Capability is registered to plugin runtime registry.

## Drop-In Trial (No Restart)

- Put a new plugin folder under `extensions/<your_plugin>/` with:
  - `promethea.plugin.json`
  - `plugin.py` (or `__init__.py`)
- On the next API request, runtime performs a throttled plugin refresh check.
- If changed, the new plugin is auto-registered into the active registry.
- For channel plugins, newly discovered channels are hot-registered and auto-started when allowed by gateway config.

Plugin ops endpoints:

- `GET /api/plugins/catalog`
- `POST /api/plugins/validate`
- `POST /api/plugins/apply`

## Engineering Rules

- Plugin init failures should degrade gracefully and not crash the full runtime.
- Manifest metadata should stay accurate (`id`, `kind`, `version`, config schema).
- Plugin capability should be exposed through runtime contracts, not hidden side effects.
