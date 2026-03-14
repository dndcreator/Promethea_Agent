# Config Model (Backlog 015)

## Goals

Backlog 015 establishes a minimal governance baseline for configuration evolution:
- explicit `config_version`
- executable migration path
- deprecation warning reporting
- scoped configuration access APIs

## Versioning and Migration

Implemented in:
- `gateway/config_migrations.py`

Key behavior:
- detect legacy configs without `config_version`
- migrate to current version (`1`)
- produce migration report (`from_version`, `to_version`, `applied_steps`, `warnings`)

## Configuration Boundaries

Current boundary sections (introduced in migration layer, backward compatible):
- `runtime_config`
- `user_preferences`
- `security_config`
- `channel_config`

Legacy top-level keys remain readable for compatibility.

## Scoped Access

`ConfigService` now supports scoped queries:
- `get_runtime_config(user_id, scope=...)`
- `get_user_preferences(user_id, scope=...)`
- `get_tool_policy_config(user_id, agent_id)`
- `get_channel_config(channel_id, user_id)`

HTTP endpoints:
- `GET /api/config/runtime/scoped`
- `GET /api/config/preferences`
- `GET /api/config/tool-policy`
- `GET /api/config/channel/{channel_id}`

## Deprecation Warnings

`ConfigService` tracks and exposes deprecation warnings per user/default context:
- `get_deprecation_warnings(user_id)`
- included in `/api/config` response and `diagnose_config`

Current example:
- legacy `system.version` flagged in favor of `config_version`
