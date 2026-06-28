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
- `GET /api/extensions/catalog`
- `POST /api/extensions/reload`
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

- `POST /api/memory/cluster/{session_id}`
- `GET /api/memory/concepts/{session_id}`
- `POST /api/memory/summarize/{session_id}`
- `GET /api/memory/summaries/{session_id}`
- `GET /api/memory/summary/{summary_id}`
- `GET /api/memory/graph`
- `GET /api/memory/graph/{session_id}`
- `GET /api/memory/capabilities`
- `GET /api/memory/entries`
- `POST /api/memory/entries`
- `PATCH /api/memory/entries/{memory_id}`
- `DELETE /api/memory/entries/{memory_id}`
- `GET /api/memory/write-decisions`
- `GET /api/memory/write-proposals`
- `POST /api/memory/write-proposals/{proposal_id}/decision`
- `GET /api/memory/dev/dashboard`
- `POST /api/memory/decay/{session_id}`
- `POST /api/memory/cleanup/{session_id}`
- `GET /api/memory/forgetting/stats/{session_id}`
- `GET /api/memory/recall/runs`
- `GET /api/memory/recall/{target_request_id}`

### Workflow and Workspace

- `POST /api/workflow/define`
- `GET /api/workflow/list`
- `POST /api/workflow/start`
- `GET /api/workflow/run/{workflow_run_id}`
- `POST /api/workflow/pause/{workflow_run_id}`
- `POST /api/workflow/resume/{workflow_run_id}`
- `POST /api/workflow/retry`
- `POST /api/workflow/approve`
- `GET /api/workflow/checkpoints/{workflow_run_id}`
- `POST /api/workspace/create-document`
- `POST /api/workspace/update-document`
- `GET /api/workspace/list-artifacts`
- `POST /api/workspace/snapshot-artifact`

### Files and Search

- `POST /api/files/upload`
- `GET /api/files`
- `GET /api/search`

Uploaded files are persisted per user. Text-like files are extracted for search and chat attachment context. Image uploads are accepted for storage and optional OCR extraction. During chat, attachments are passed to `ConversationService` as structured runtime input: text/document files become labeled text context, while image files are sent as native image blocks when the active model is vision-capable. Text-only models receive OCR/text fallback or an explicit unavailable-attachment notice.

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
- `GET /api/config/soul`

### Org Brain (B-side Context)

- `GET /api/org-brain/status`
- `POST /api/org-brain/ingest`
- `POST /api/org-brain/ingest-file` (`multipart/form-data`, field name: `file`)
- `POST /api/org-brain/recall`

### Voice

Voice routes are experimental/provider-dependent in the current preview. They are listed for contract discovery, but voice input is not a supported release feature. A DeepSeek-only chat configuration does not provide STT/audio transcription; `/api/voice/stt` and `/api/voice/ptt` require an OpenAI-compatible audio transcription provider.

- `GET /api/voice/capabilities`
- `POST /api/voice/stt`
- `POST /api/voice/tts`
- `POST /api/voice/turn`
- `POST /api/voice/ptt`

### Ops and Discovery

- `GET /api/status`
- `GET /api/bootstrap` - public first-run UI status, including configured backend, Neo4j availability, registration availability, and restart requirement for backend changes.
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

Chat response may include:
- `memory_visibility`: memory recall/write feedback summary for UI rendering.
- `prompt_assembly`: prompt block usage/compaction debug snapshot.
- `soul`: current user-scoped soul prompt summary (`content`, `version`, `updated_at`).

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
