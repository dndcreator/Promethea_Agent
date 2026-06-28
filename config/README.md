# Config Module

Promethea keeps sensitive runtime settings separate from non-secret behavior settings.

## Config Model

Config precedence, from low to high:

1. `config/default.json`
2. `config/users/<user_id>/config.json`
3. environment variables and user `secrets.env`

## Key Objectives

- stable reusable defaults
- user-level non-secret overrides
- centralized secret management through environment files

## Key Files

- `config/default.json`: default system config
- `config/users/<user_id>/config.json`: user overrides, ignored by git
- `config.py`: schema and loading logic

## Example

User updates agent name:

1. Frontend calls config update endpoint.
2. Backend persists the value to per-user config.
3. Next load merges default config and user overrides.

## Change Notes

- Keep defaults, schema, and UI fields in sync.
- Avoid introducing parallel write paths.
- Verify precedence behavior after each config change.
