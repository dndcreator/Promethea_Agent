# Protocol Surface

Promethea exposes a protocol-discoverable runtime.

## Primary Discovery Endpoints

- `GET /api/ops/protocol`
- `GET /api/ops/methods`
- `GET /api/ops/http-contracts`
- `GET /api/ops/surfaces`
- `GET /api/ops/framework-check`
- `GET /api/ops/readiness`

## Contract Rule

Do not hardcode route assumptions when integration can consume discovery endpoints.

## Runtime Shape

- HTTP routes under `/api/*`
- WebSocket gateway under `/gateway/ws/{device_id}`
- UI and CLI are reference clients over the same backend capabilities
