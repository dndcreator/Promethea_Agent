# API Reference (v1)

This document defines the externally consumable runtime API surface for Promethea.

## Project Metadata

Project routes require the current authenticated user. `GET /api/projects` returns `{projects: Project[]}`; `POST /api/projects` accepts `{name}` and returns the created `Project` (201). `PATCH /api/projects/{project_id}` renames it. `DELETE /api/projects/{project_id}` returns 204 and only removes grouping metadata. `PUT /api/sessions/{session_id}/project` accepts `{project_id: string | null}` and returns 204; both objects must belong to the current user. Unknown or foreign objects return 404. Names contain 1-100 nonblank characters.

`Project` is defined in `gateway/public_contracts.py` and generated into the SDK. A project groups conversations; it does not rename, merge, or create execution workspaces. Project records are included in personal workspace archives and legacy personal bundles when exporting sessions.

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
5. Start with chat plus the tool/extension discovery routes

This avoids hardcoding stale assumptions.

## Core HTTP Domains

### Messaging Platforms

- `POST /api/channels/{channel}/webhook`: QQ raw-body Ed25519 / Telegram Secret Token authentication, not a user JWT. Durable acceptance precedes acknowledgement; unbound/unsupported events do not invoke the model.
- `GET /api/channels`: current user's platform availability and bindings.
- `POST /api/channels/pairings`: `{channel: registered_provider_id}` -> generated `ChannelPairing`, valid for 10 minutes. The provider must expose the authenticated Webhook contract; send its command in a verified bot private chat.
- `DELETE /api/channels/{channel}/binding`: revoke current-user bindings even when the provider is disabled.
- `GET /api/channels/deliveries`: current user's `ChannelDelivery[]`, without payloads or credentials.
- `POST /api/channels/deliveries/{delivery_id}/retry`: retry a provider-rejected persisted reply only; foreign records return 404, ambiguous/non-retryable outcomes 409.

Controls require the current Promethea user. Public types originate in
`gateway/public_contracts.py`; the SDK exposes `client.channels`. The legacy
`/api/user/channels/bind` cannot claim QQ/Telegram identities by raw ID.
See [operational boundaries](channels/README.md).

### Chat and Conversation

- `POST /api/chat`
- `POST /api/chat/confirm`
- `POST /api/chat/{session_id}/steer`
- `POST /api/followup`

Chat requests may include an owned `task_id` to bind the run to durable Task
goal state. This applies to HTTP, SSE and the TypeScript SDK; omission keeps
ordinary conversation behavior. Task read models expose `goal_gaps` without
internal monitoring frames or execution tokens.

Streaming `text` events contain `content` and an optional `operation`:
`delta` (the legacy default) appends, while `replace` replaces the current draft,
including clearing it with empty content. The final `done.content` is the
committed assistant answer. Consumers must handle replacement to avoid retaining
invalid or superseded drafts. SSE comment heartbeats do not alter content.

The authenticated steer endpoint accepts generated `RunSteerRequest`:
`{conversation_turn_id, message_id, message}`. It persists a bounded instruction
for the exact current user/session/turn and returns `RunSteerResponse` with
`queued` or `applied`. Retry the same ID and text after uncertain delivery;
conflicting content returns 409. The stream's `steering` event reports applied
command IDs. History preserves guidance as user messages with `steering_id` and
`steering_status`; unconsumed settled guidance is `not_applied`.
Unknown/foreign sessions return 404; inactive, preparing, confirmation-waiting
or finalizing turns return 409. Instructions apply at Action safe boundaries,
not by cancelling running tools. No approvals or additional budget are granted.
See the [SDK streaming contract](../sdk/typescript/README.md#streaming-and-steering).

### Tools and Extensions

- `GET /api/extensions/catalog`
- `POST /api/extensions/reload`
- `GET /api/status/tools`

Tool execution is mediated by `CapabilityService` rather than a public `POST /api/tools/call` endpoint. Discover callable tools through the status and extension catalog endpoints, then drive tool use through chat, task, or workflow routes.

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
- `GET /api/memory/graph/search`
- `GET /api/memory/graph/{session_id}`
- `GET /api/memory/capabilities`
- `GET /api/memory/cognition`
- `GET /api/memory/entries`
- `GET /api/memory/search`
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

### Workflow

- `POST /api/workflow/define`
- `GET /api/workflow/list`
- `POST /api/workflow/start`
- `GET /api/workflow/run/{workflow_run_id}`
- `POST /api/workflow/pause/{workflow_run_id}`
- `POST /api/workflow/resume/{workflow_run_id}`
- `POST /api/workflow/retry`
- `POST /api/workflow/approve`
- `GET /api/workflow/checkpoints/{workflow_run_id}`

### Tasks and Workbench

- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `PATCH /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/runs`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/workbench/snapshot`
- `GET /api/workbench/stream`

Tasks own durable work independently of conversations. Workbench exposes the
read model and resumable event stream; clients do not own task lifecycle state.

### Canvas Environments

- `GET /api/canvas/environments`
- `GET /api/canvas/{workspace_id}/{environment_id}/preview/{asset_path}`
- `WS /api/canvas/{workspace_id}/{environment_id}/preview/{asset_path}`

Canvas previews are authenticated and confined to registered workspace environments.

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
- `GET /health`
- `GET /api/health/memory`
- `GET /api/ops/capabilities`
- `GET /api/ops/schema`
- `GET /api/ops/abstractions`
- `GET /api/ops/protocol`
- `GET /api/ops/readiness`
- `GET /api/ops/http-contracts`
- `GET /api/ops/methods`
- `GET /api/ops/framework-check`
- `GET /api/ops/surfaces`
- `GET /api/ops/governance`
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
    "requested_mode": "auto"
  }'
```

Chat response may include:
- `memory_visibility`: memory recall/write feedback summary for UI rendering.
- `prompt_assembly`: prompt block usage/compaction debug snapshot.
- `soul`: current user-scoped soul prompt summary (`content`, `version`, `updated_at`).

### Example: list callable tools

```bash
curl http://127.0.0.1:8000/api/status/tools
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
