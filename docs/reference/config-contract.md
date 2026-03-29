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
