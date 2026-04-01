# API Reference (v1)

This document defines the externally consumable runtime API surface for Promethea.

## Positioning

Promethea backend is the canonical runtime.
- Web UI is a client.
- CLI is a client.
- Third-party apps/agents should also be clients.

If your integration reads this page, your main objective is contract stability.

## Integration Path (Recommended)

1. Discover runtime surfaces: `GET /api/ops/surfaces`
2. Pull protocol/method contracts: `GET /api/ops/protocol` and `GET /api/ops/methods`
3. Pull HTTP contract index: `GET /api/ops/http-contracts`
4. Validate readiness: `GET /api/ops/readiness`
5. Start with one chat route and one tool route

This avoids hardcoding stale assumptions.

## Core HTTP Domains

### Chat and Conversation

- `POST /api/chat`
- `POST /api/chat/confirm`
- `POST /api/followup`

### Tools and MCP

- `GET /api/tools`
- `POST /api/tools/call`
- `GET /api/mcp/services`
- `GET /api/mcp/services/{name}/health`
- `GET /api/mcp/services/{name}/tools`
- `GET /api/mcp/visible-tools`

### Skills

- `GET /api/skills/catalog`
- `GET /api/skills/{skill_id}`
- `POST /api/skills/install`
- `POST /api/skills/activate`

### Memory

- `POST /api/memory/query`
- `POST /api/memory/cluster`
- `POST /api/memory/summarize`
- `GET /api/memory/graph`
- `POST /api/memory/decay`
- `POST /api/memory/cleanup`
- `GET /api/memory/recall/runs`
- `GET /api/memory/recall/inspect`

### Workflow and Workspace

- `POST /api/workflow/define`
- `GET /api/workflow/list`
- `POST /api/workflow/start`
- `GET /api/workflow/status`
- `POST /api/workflow/pause`
- `POST /api/workflow/resume`
- `POST /api/workflow/retry-step`
- `POST /api/workflow/approve-step`
- `GET /api/workflow/checkpoints`
- `POST /api/workspace/create-document`
- `POST /api/workspace/update-document`
- `GET /api/workspace/list-artifacts`
- `POST /api/workspace/snapshot-artifact`

### Config and Runtime Preferences

- `GET /api/config`
- `POST /api/config/update`
- `POST /api/config/reset`
- `POST /api/config/switch-model`
- `GET /api/config/diagnose`
- `GET /api/config/effective`
- `GET /api/config/default-template`
- `GET /api/config/contract`
- `GET /api/config/ui-schema`

### Voice

- `GET /api/voice/capabilities`
- `POST /api/voice/stt`
- `POST /api/voice/tts`
- `POST /api/voice/turn`
- `POST /api/voice/ptt`

### Ops and Discovery

- `GET /api/status`
- `GET /api/health`
- `GET /api/ops/capabilities`
- `GET /api/ops/abstractions`
- `GET /api/ops/protocol`
- `GET /api/ops/readiness`
- `GET /api/ops/http-contracts`
- `GET /api/ops/methods`
- `GET /api/ops/framework-check`
- `GET /api/ops/surfaces`
- `GET /api/ops/runbook`

## WebSocket Contract

Request envelope:
- `type`: `req`
- `id`: unique request id
- `method`: `RequestType` enum value
- `params`: request payload object

Response envelope:
- `type`: `res`
- `id`: request id
- `ok`: boolean
- `payload`: object on success
- `error`: string on failure

Event envelope:
- `type`: `event`
- `event`: `EventType`
- `payload`: event payload

Method catalog is discoverable via `GET /api/ops/methods`.

## Error Contract

HTTP and WS use normalized fields:
- `code`
- `message`
- `retryable`
- `dependency`
- `advice`
- `trace_id`

For WS, normalized details are typically in `payload.error_detail`.

## Minimal Examples

### Example: chat turn

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Plan my tasks for today",
    "session_id": "s1",
    "mode": "auto"
  }'
```

### Example: list callable tools

```bash
curl http://127.0.0.1:8000/api/tools
```

### Example: list skill catalog

```bash
curl http://127.0.0.1:8000/api/skills/catalog -H "X-User-Id: u1"
```

### Example: discover contracts before integration

```bash
curl http://127.0.0.1:8000/api/ops/surfaces
curl http://127.0.0.1:8000/api/ops/http-contracts
```

## Versioning Policy

- Current contract version: `v1`
- Additive changes are allowed in `v1`
- Breaking changes require explicit version bump

Clients should prefer discovery endpoints over hardcoded assumptions.

## Notes for Agent-to-Agent Integrators

- Treat `/api/ops/*` as negotiation layer.
- Treat `/api/config/contract` as ownership/secret boundary source.
- Treat readiness and service health as runtime preconditions.
- Assume degraded dependencies can happen and handle partial availability.
