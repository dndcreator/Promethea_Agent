# Configuration Contract

Primary pages:
- [Configuration Guide](../configuration.md)
- [Config API Reference](../api-reference.md)

Runtime contract endpoints:
- `GET /api/config/contract`
- `GET /api/config/default-template`
- `GET /api/config/effective`
- `GET /api/config/ui-schema`

Key principles:
- defaults define baseline behavior for new users
- user config overrides defaults
- secrets remain env-managed

Additional memory keys:
- memory.raw_log (append-only write-ahead log and replay)
- memory.hippocampus (idle/background consolidation cadence for warm/cold layers)

Procedural-memory runtime note:
- reasoning/action procedural assets are persisted under `brain/basal_ganglia` (not user profile config fields)
