# Documentation Gaps and Reality Check

This report tracks documentation risks that affect public trust and adoption.
Each item is based on current repository behavior and is labeled with a status.

Status values:

- `OPEN`: still missing, action needed
- `RESOLVED`: verified and aligned
- `NEEDS_DECISION`: product choice required before final docs

Severity values:

- `BLOCKER`: cannot document safely without misleading users
- `MAJOR`: can document with caveats, but credibility risk remains
- `MINOR`: lower impact or narrow scope

---

## 1) Workflow demo endpoint mismatch

- Status: `RESOLVED`
- Severity: `BLOCKER` (historically)

Current state:

- Scenario doc uses `POST /api/workflow/start`
- Route exists in `gateway/http/routes/workflow.py`

Action:

- Keep current scenario endpoint (`/api/workflow/start`)
- No further action required unless API shape changes

---

## 2) Memory backend cold-start behavior unclear

- Status: `RESOLVED` in docs update
- Severity: `BLOCKER`

Verified behavior:

- If memory is disabled, service still starts and memory features are disabled.
- If `neo4j` is configured but unreachable, service still starts; memory is not ready.
- No automatic fallback from `neo4j` to `sqlite_graph` or `flat_memory`.

Action:

- Keep these rules explicit in `docs/configuration.md`
- Use `/api/health/memory` for operational checks

---

## 3) Memory write gate integration not verified

- Status: `RESOLVED`
- Severity: `BLOCKER` (historically)

Verified behavior:

- `MemoryService` calls `MemoryWriteGate.evaluate(...)` before final memory persistence path.

Action:

- Keep architecture docs aligned with this call path

---

## 4) Reasoning mode claims vs runtime reality

- Status: `RESOLVED`
- Severity: `MAJOR`

Verified behavior:

- Config validation enforces `reasoning.mode == react_tot` for `reasoning` config.

Action:

- Continue documenting `react_tot` as the only supported reasoning config mode
- If new modes are introduced, update both validator and docs together

---

## 5) Skills registry and official pack path uncertainty

- Status: `RESOLVED`
- Severity: `MAJOR` (historically)

Verified behavior:

- `skills/registry.py` exists
- official scaffold exists under `skills/packs/official/coding_copilot`

Action:

- Keep playbooks synchronized with real loader behavior

---

## 6) Telegram docs over-claim risk

- Status: `RESOLVED` (with explicit scope)
- Severity: `MAJOR`

Current reality:

- Telegram adapter exists.
- Full first-party bot token/webhook runtime wiring is not documented or fully exposed as a config-driven built-in flow.

Action:

- Document Telegram as adapter-level integration today
- Avoid claiming fully managed Telegram runtime setup unless implemented

---

## 7) Web UI capability and limits undocumented

- Status: `RESOLVED`
- Severity: `MAJOR`

Action completed:

- Added `docs/ui-overview.md` and linked from README

---

## 8) `API__FAILOVER_MODELS` implementation ambiguity

- Status: `NEEDS_DECISION`
- Severity: `MAJOR`

Current reality:

- Field exists in schema/config docs.
- Runtime automatic model failover path is not clearly wired as a guaranteed feature.

Action options:

1. Implement runtime failover and tests.
2. Keep as advanced reserved field in public docs (current choice).

---

## 9) Sandbox profile semantics (`off/dev/strict`) are underspecified

- Status: `RESOLVED` (documented as current behavior)
- Severity: `MINOR`

Current reality:

- `profile` is validated and stored.
- It should not be described as auto-overriding command/network/workspace settings unless code enforces that mapping.

Action:

- Keep docs explicit: set `workspace_access`, `command_mode`, and `network_mode` directly

---

## 10) `/api/health/memory` endpoint missing

- Status: `RESOLVED`
- Severity: `MINOR`

Action completed:

- Added `GET /api/health/memory` in `gateway/http/routes/status.py`
- Updated playbook example output shape

---

## Priority summary (current)

1. `NEEDS_DECISION`: runtime failover (`API__FAILOVER_MODELS`)
2. Keep docs-code sync as part of release checklist for workflow/memory/ui/telegram sections
