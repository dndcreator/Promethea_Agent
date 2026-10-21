# Web UI Overview

This document describes what the built-in Web UI currently supports and what remains API-only.

UI entrypoint:

- `http://127.0.0.1:5173`

## What you can do in the UI today

- Sign up / log in with user identity isolation.
- Open diagnostics before sign-in. Identity is independent of the selected memory backend; memory availability is not a condition for account existence. The login screen includes a diagnostics entry and can be dismissed without signing in.
- Chat with streaming responses (when stream mode is enabled).
- Manage sessions and continue previous conversations.
- Group conversations into persistent projects, rename groups, move conversations, and pin sessions. Projects are organizational metadata, not sandbox/execution workspaces; deleting a project leaves its conversations intact. Groups and memberships are included in personal workspace transfer.
- Monitor cross-conversation Tasks from a separate Tasks page and issue revision-aware pause/resume/cancel commands. Workflow definitions and runs remain a separate surface.
- Open individual Task runs in a run-scoped Workbench. Run inspection does not expose Task control commands; return to the whole-Task view to operate on its current state. Related conversation links use stored titles when available.
- Chat usage is secondary toolbar information: request tokens, Runtime total tokens, and completed-request duration are separate readings; unavailable values remain unknown. Provider reasoning stays in its existing expandable process view.
- Failed/interrupted turns retain the original request and a separate Runtime status, not a synthetic assistant answer. Empty historical sessions remain selected rather than showing the new-chat homepage. Provider output-limit errors and empty responses are distinguished; a retry is explicit.
- Provider thoughts disclose one model step at a time with a bounded preview and scrollable full text. Workbench cards keep technical JSON behind a second disclosure while preserving resource actions. UI language is sent with chat requests; original provider text is not translated by an extra model call.
- Upload, search, select, and attach user files. The file detail shows only the text preview/snippet returned by the backend, not a full-document editor. Search results open the exact file ID even when names are duplicated. Failed uploads retain the chosen file for retry.
- Search across sessions and uploaded files from the global search panel.
- Inspect workflow definitions, personal workflow runs, and recoverable runs. Pause/resume is exposed for existing runs; workflow authoring stays API/workflow-engine driven.
- Open Settings:
  - Quick Setup shows only the key fields.
  - Enterprise Brain is controlled by `org_brain.enabled`; when disabled, enterprise upload/recall/graph entrypoints are hidden and the UI asks the user to restart after changing the switch.
  - Advanced capabilities are folded by default.
  - Application/tool authoring is explicitly enabled under Advanced Capabilities. Leave Canvas browser selection on Automatic to reuse a browser or prepare managed Chromium; an explicit installed channel remains optional. The browser runs in a separate sandboxed context, not the user's signed-in profile. Reasoning-only models may require a larger output-token limit; the UI never increases it automatically.
  - Personalization shows `Soul Prompt` as read-only (view-only in UI).
  - Personal workspace and plugin capabilities live under the advanced foldout.
- View metrics panel (token/cost/runtime counters).
- Run doctor checks and basic diagnostics.
- Export or restore a portable personal workspace archive from Settings. Replacement requires explicit confirmation. After restoration, refresh configuration and reset stale conversation, Task, and Canvas views; retain the restore receipt and report partial failures.

## Configuration UX model

- The UI loads full config data from the backend.
- It intentionally does not show all options at once.
- Sensitive values are redacted in responses and env-only secret keys are ignored on save.
- `persona.soul` is intentionally excluded from editable form submission.
- The backend may evolve `persona.soul.content` automatically; UI only displays it.
- This keeps soul evolution isolated from manual prompt edits while still giving visibility.
- Advanced config surfaces should default to collapsed unless they are required for first-run setup or a core B-side capability.

## Frontend interface map

An icon-only rail selects feature pages. Projects and conversations occupy a separate collapsible sidebar. The central chat stays mounted while another feature is open. The right Workbench offers Work (outputs, previews, references, review) and Activity (folded execution records), and becomes an overlay on narrower screens. Canvas previews stay mounted when switching Workbench tabs. Chat and Workbench reuse one subscription for the conversation scope; an explicitly observed Task has its own scope. UI components do not infer Task completion or tool success.

Use this map when rebuilding the Web UI. Layout can change, but these function surfaces should remain reachable unless the product scope changes.

| UI surface | Primary behavior | Backend interface |
| --- | --- | --- |
| Auth modal | Sign up, log in, and keep user isolation through the backend-independent identity store. | `/api/auth/*` through `AuthContext` |
| Chat console | Stream chat, continue or create sessions, show tool events and confirmation requests. | `POST /api/chat`, `GET /api/sessions/{session_id}`, `POST /api/chat/confirm` |
| Projects and conversations | Create, rename, delete groups; assign/unassign conversations without changing their execution identity. | SDK over `/api/projects`, `/api/projects/{project_id}`, `PUT /api/sessions/{session_id}/project`; existing session pin API |
| Tasks | List cross-conversation Tasks, inspect objective and runs, open their Workbench, pause/resume/cancel using expected revision. | SDK over `GET /api/tasks`, `/api/tasks/{task_id}/*` |
| File panel | Upload a user file into the backend file store; list, search, and attach extracted text to the next chat turn. | `POST /api/files/upload`, `GET /api/files?q=&limit=` |
| Global search | Search conversations and uploaded files; selecting a session reopens it. | `GET /api/search?q=&limit_sessions=&limit_files=` |
| Cognition Workbench | Explore the user-scoped Cognition Bundle as a calm space or grouped list, inspect/edit stored memory, and resolve pending write proposals. | SDK over `/api/memory/cognition`, plus `/api/memory/entries` and `/api/memory/write-proposals/*` |
| Workflow inspector | Inspect definitions, personal runs, recoverable runs, and pause/resume existing runs. | `/api/workflow/list`, `/api/workflow/run/{workflow_run_id}`, `/api/workflow/pause/{workflow_run_id}`, `/api/workflow/resume/{workflow_run_id}`, `/api/personal/workflow/*` |
| Settings | Edit basic runtime config, keep advanced options folded, control enterprise brain visibility, and show read-only soul state. | `/api/config`, `/api/config/update`, `/api/config/soul`, `/api/org-brain/status`, `/api/plugins/catalog`, `/api/personal/templates/catalog` |
| Personal workspace | Export or restore one portable user-record archive. | `POST /api/personal/workspace/archive`, `POST /api/personal/workspace/restore` |
| Extensions & tools | Inspect tool packages in one catalog, view callable tools, and hot-reload manifests dropped into `extensions/community`. | `GET /api/extensions/catalog`, `POST /api/extensions/reload` |
| Metrics | Show runtime counters and operational signals. | `GET /api/metrics` |
| Doctor | Run health diagnostics and config migration helper. | `GET /api/doctor`, `POST /api/doctor/migrate-config` |
| Self-evolve | Show capability evolution status and create versioned capability drafts. | `/api/self-evolve/status`, `/api/self-evolve/tasks` |
| Canvas | Run generated applications, save app data, retain reusable copies, inspect runtime errors, and discard applications. | SDK over `/api/canvas/*`; restricted iframe MessageChannel |
| Reasoning side panel | Show active reasoning tree, inspect tree details, stop or steer active reasoning. | `/api/reasoning/active`, `/api/reasoning/tree/{tree_id}`, `/api/reasoning/tree/{tree_id}/stop`, `/api/reasoning/tree/{tree_id}/steer` |
| Agent Workbench | Follow the Task/Run projection in real time, read folded Runtime activity, and issue revision-aware pause, resume, or cancel commands. Internal events and reasoning data stay behind expandable diagnostics instead of being interpreted by React. | SDK over `GET /api/workbench/stream`, `/api/workbench/snapshot`, and `/api/tasks/{task_id}/*` |
| Voice input | Experimental/provider-dependent only; not a supported preview UI feature. DeepSeek-only chat configuration does not provide STT/audio transcription. | `POST /api/voice/ptt` |

## Memory-related behavior in UI

- Memory backend selection and migration use the runtime configuration/API, not a frontend backend-switch control. The Settings page retains its existing advanced environment-backed Neo4j connection fields.
- If memory backend is unavailable (for example Neo4j down), chat still works but memory-dependent features degrade.
- The Cognition Workbench deliberately exposes only `Cognition`, `Memory`, and `Review`.
- Cognition is a Self Model projection over real memory and pending proposals; it is not a separate store.
- Write-decision audit, recall-run, and raw graph endpoints remain available to backend diagnostics but are not product tabs.

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

- Personal workspace archives contain user records: portable preferences, sessions and text-anchored follow-ups, memory and its user-visible write audit, uploaded file originals, avatar assets, workflow history, completed reasoning history, Moirai process experience, and retained static canvas apps with their app data. They exclude API keys, passwords, tokens, deployment endpoints, browser profiles, running processes, and raw service logs. Restored in-progress workflows are paused because their original process/tool state does not exist on the new device.

- No full parity with all low-level API and internal debug endpoints by design.
- Voice input is not a supported preview feature. The current route is experimental and provider-dependent.
- Telegram bot runtime setup is not managed through this UI.
- Some operational tasks (bulk export/migration scripts) are playbook/API driven.
- Procedural memory internals (ExecutionMindGraph / basal_ganglia templates) are currently backend-visible but not fully first-class in UI editing.

## Related docs

- `docs/configuration.md`
- `docs/playbooks/how-to-change-memory-backend.md`
- `RELEASE_NOTES.md`
