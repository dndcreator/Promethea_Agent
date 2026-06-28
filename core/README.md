# Core Module

`core` implements the plugin framework: discovery, loading, registration, and runtime access.

## Key Files

- `core/services.py`: service access entrypoint
- `core/plugins/discovery.py`: plugin discovery
- `core/plugins/loader.py`: plugin loading
- `core/plugins/manifest.py`: plugin metadata model
- `core/plugins/registry.py`: capability registry
- `core/plugins/runtime.py`: runtime management
- `core/plugins/types.py`: plugin-related types

## Workflow

1. Scan `extensions/*`.
2. Parse `promethea.plugin.json`.
3. Import `plugin.py`.
4. Register capabilities into the runtime registry.

## Notes

- Plugin failures should be isolated.
- Registration keys must be unique.
- Prefer interface-based dependency over hard coupling.
