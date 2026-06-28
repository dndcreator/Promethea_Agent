# Web UI Overview

This document describes what the built-in Web UI currently supports and what remains API-only.

UI entrypoint:

- `http://127.0.0.1:5173`

## What you can do in the UI today

- Sign up / log in with user identity isolation.
- View first-run backend status before sign-in. Neo4j is the default/core graph backend; if it is configured but unavailable, registration is blocked with a clear UI message instead of silently falling back. The login screen can enter a limited setup/diagnostics mode.
- Chat with streaming responses (when stream mode is enabled).
- Manage sessions and continue previous conversations.
- Upload and list user files. Uploaded files are stored through the backend file store and are available to search/export flows.
- Search across sessions and uploaded files from the global search panel.
- Inspect workflow definitions, personal workflow runs, and recoverable runs. Pause/resume is exposed for existing runs; workflow authoring stays API/workflow-engine driven.
- Open Settings:
  - Quick Setup shows only the key fields.
  - Enterprise Brain is controlled by `org_brain.enabled`; when disabled, enterprise upload/recall/graph entrypoints are hidden and the UI asks the user to restart after changing the switch.
  - Advanced capabilities are folded by default.
  - Personalization shows `Soul Prompt` as read-only (view-only in UI).
  - Personal workspace and plugin capabilities live under the advanced foldout.
- View metrics panel (token/cost/runtime counters).
- Run doctor checks and basic diagnostics.

## Configuration UX model

- The UI loads full config data from the backend.
- It intentionally does not show all options at once.
- Sensitive values are redacted in responses and env-only secret keys are ignored on save.
- `persona.soul` is intentionally excluded from editable form submission.
- The backend may evolve `persona.soul.content` automatically; UI only displays it.
- This keeps soul evolution isolated from manual prompt edits while still giving visibility.
- Advanced config surfaces should default to collapsed unless they are required for first-run setup or a core B-side capability.

## Frontend interface map

Use this map when rebuilding the Web UI. Layout can change, but these function surfaces should remain reachable unless the product scope changes.

| UI surface | Primary behavior | Backend interface |
| --- | --- | --- |
| Auth modal | Sign up, log in, keep user isolation, and explain backend-dependent registration failures before sign-in. | `/api/bootstrap`, `/api/auth/*` through `AuthContext` |
| Chat console | Stream chat, continue or create sessions, show tool events and confirmation requests. | `POST /api/chat`, `GET /api/sessions/{session_id}`, `POST /api/chat/confirm` |
| File panel | Upload a user file into the backend file store; list, search, and attach extracted text to the next chat turn. | `POST /api/files/upload`, `GET /api/files?q=&limit=` |
| Global search | Search conversations and uploaded files; selecting a session reopens it. | `GET /api/search?q=&limit_sessions=&limit_files=` |
| Memory inspector | Inspect memory entries, write decisions, recall runs, and graph data; edit/delete entries where supported. | `/api/memory/entries`, `/api/memory/write-decisions`, `/api/memory/recall/*`, `/api/memory/graph` |
| Workflow inspector | Inspect definitions, personal runs, recoverable runs, and pause/resume existing runs. | `/api/workflow/list`, `/api/workflow/run/{workflow_run_id}`, `/api/workflow/pause/{workflow_run_id}`, `/api/workflow/resume/{workflow_run_id}`, `/api/personal/workflow/*` |
| Settings | Edit basic runtime config, keep advanced options folded, control enterprise brain visibility, and show read-only soul state. | `/api/config`, `/api/config/update`, `/api/config/soul`, `/api/org-brain/status`, `/api/plugins/catalog`, `/api/personal/templates/catalog` |
| Extensions & tools | Inspect official/community extensions in one catalog, view callable tools, and hot-reload community manifests dropped into `extensions/community`. | `GET /api/extensions/catalog`, `POST /api/extensions/reload` |
| Metrics | Show runtime counters and operational signals. | `GET /api/metrics` |
| Doctor | Run health diagnostics and config migration helper. | `GET /api/doctor`, `POST /api/doctor/migrate-config` |
| Self-evolve | Show enabled/disabled state, task audit stats, store path, and create explicitly targeted evolution tasks. | `/api/self-evolve/status`, `/api/self-evolve/tasks` |
| Reasoning side panel | Show active reasoning tree, inspect tree details, stop or steer active reasoning. | `/api/reasoning/active`, `/api/reasoning/tree/{tree_id}`, `/api/reasoning/tree/{tree_id}/stop`, `/api/reasoning/tree/{tree_id}/steer` |
| Voice input | Experimental/provider-dependent only; not a supported preview UI feature. DeepSeek-only chat configuration does not provide STT/audio transcription. | `POST /api/voice/ptt` |

## Memory-related behavior in UI

- Memory can be enabled/disabled from settings.
- Backend selection is exposed (`neo4j`, `sqlite_graph`, `flat_memory`).
- If memory backend is unavailable (for example Neo4j down), chat still works but memory-dependent features degrade.

## Attachment and multimodal behavior

- File upload is first a user file store feature, not a guarantee that the active model can see arbitrary binary content.
- Text-like files (`txt`, `md`, `csv`, `json`, `docx`, `pdf`) are extracted to text and can be attached to the next chat turn.
- Image files (`png`, `jpg`, `jpeg`, `webp`, `gif`) can be stored. If optional OCR dependencies are installed, extracted OCR text can be used as chat context.
- If no text can be extracted, the UI marks the file as stored-only. During chat, the runtime can pass stored images as native image input when the active model supports vision; otherwise the prompt receives a clear unavailable-attachment note instead of inventing visual/audio details.
- Voice remains a separate experimental push-to-talk route through `/api/voice/ptt`; it requires an audio transcription provider and is not covered by the DeepSeek-only setup path.
- This keeps chat, reasoning, memory, and search compatible with attachments without pretending every backend model supports native vision or audio input.

Use API health for exact runtime state:

```bash
curl "http://127.0.0.1:8000/api/health/memory"
```

## Current limitations

- No full parity with all low-level API and internal debug endpoints by design.
- Voice input is not a supported preview feature. The current route is experimental and provider-dependent.
- Telegram bot runtime setup is not managed through this UI.
- Some operational tasks (bulk export/migration scripts) are playbook/API driven.
- Procedural memory internals (ExecutionMindGraph / basal_ganglia templates) are currently backend-visible but not fully first-class in UI editing.

## Related docs

- `docs/configuration.md`
- `docs/playbooks/how-to-change-memory-backend.md`
- `docs/operations/release-readiness.md`
