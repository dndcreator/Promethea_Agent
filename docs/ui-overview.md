# Web UI Overview

This document describes what the built-in Web UI currently supports and what remains API-only.

UI entrypoint:

- `http://127.0.0.1:8000/UI/index.html`

## What you can do in the UI today

- Sign up / log in with user identity isolation.
- Chat with streaming responses (when stream mode is enabled).
- Manage sessions and continue previous conversations.
- Open Settings:
  - Quick Setup shows only the key fields.
  - Advanced Settings contains the full configuration form.
  - Personalization shows `Soul Prompt` as read-only (view-only in UI).
- View metrics panel (token/cost/runtime counters).
- Run doctor checks and basic diagnostics.

## Configuration UX model

- The UI loads full config data from the backend.
- It intentionally does not show all options at once.
- Sensitive values are redacted in responses and env-only secret keys are ignored on save.
- `persona.soul` is intentionally excluded from editable form submission.
- The backend may evolve `persona.soul.content` automatically; UI only displays it.
- This keeps soul evolution isolated from manual prompt edits while still giving visibility.

## Memory-related behavior in UI

- Memory can be enabled/disabled from settings.
- Backend selection is exposed (`neo4j`, `sqlite_graph`, `flat_memory`).
- If memory backend is unavailable (for example Neo4j down), chat still works but memory-dependent features degrade.

Use API health for exact runtime state:

```bash
curl "http://127.0.0.1:8000/api/health/memory"
```

## Current limitations

- No full parity with all low-level API and internal debug endpoints.
- Telegram bot runtime setup is not managed through this UI.
- Some operational tasks (bulk export/migration scripts) are playbook/API driven.
- Procedural memory internals (ExecutionMindGraph / basal_ganglia templates) are currently backend-visible but not fully first-class in UI editing.

## Related docs

- `docs/configuration.md`
- `docs/playbooks/how-to-change-memory-backend.md`
- `docs/scenario-workflow-audit.md`
