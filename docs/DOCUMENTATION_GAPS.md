# Documentation Gaps — Implementation Insufficiency Report

This document records the places where the current implementation is either incomplete or inconsistent in ways that prevent writing authoritative public documentation.  
Each item is rated by severity and has a suggested engineering action.

**Severity levels:**  
- 🔴 **Blocker** — Cannot write accurate docs; docs would be misleading.  
- 🟠 **Major** — Docs possible but with significant caveats; reduces credibility.  
- 🟡 **Minor** — Docs possible; caveats are minor or temporary.

---

## 1. 🔴 No `start_gateway_service.py` or clear main entry point visible in docs

**What's missing:**  
`start_gateway_service.py` exists and is functional, but there is no documented API contract for what `plan_and_save` or other high-level workflow endpoints do.  
The scenario doc (`docs/scenario-workflow-audit.md`) references `POST /api/workflows/plan_and_save` — but this route may not be implemented in `gateway/http/routes/workflow.py`.

**Impact on docs:**  
The signature demo in the scenario doc may silently fail for anyone trying it.

**Action required:**  
Verify that `POST /api/workflows/plan_and_save` exists and behaves as documented, or replace the demo endpoint with one that actually exists.

---

## 2. 🔴 Memory backend selector (`MEMORY__STORE_BACKEND`) cold-start behavior is undocumented

**What's missing:**  
When `MEMORY__STORE_BACKEND=neo4j` but Neo4j is unreachable, does the system:
- Fail hard on startup?
- Fall back to `flat_memory` silently?
- Fail requests that require memory but continue serving others?

The code path in `memory/adapter.py → _init_memory_system` determines this, but the behavior is not documented anywhere.

**Impact on docs:**  
First-time users who don't have Neo4j will be confused by silent failures or hard crashes.

**Action required:**  
Document the fallback behavior in `docs/configuration.md`, and ideally add a `GET /api/health/memory` endpoint that reports the active backend and its readiness.

---

## 3. 🔴 `MemoryWriteGate` is implemented but its integration into the main chat path is unclear

**What's missing:**  
`MemoryWriteGate` is correctly implemented in `gateway/memory_gate.py` and its logic is solid.  
However, it is unclear whether `ConversationPipeline` (the main chat path) actually calls it before every long-term write, or if this is only used in specific code paths.

**Impact on docs:**  
Cannot accurately claim "all memory writes go through the write gate" without verifying the call path in `gateway/conversation_pipeline.py` and `gateway/memory_service.py`.

**Action required:**  
Trace the call chain from `ConversationPipeline._run` → `memory_service.add_message` → `MemoryWriteGate.evaluate`.  
If any path bypasses the gate, document it as a known gap or fix it.

---

## 4. 🟠 Reasoning mode documentation says only `react_tot` is supported, but this is not verified

**What's missing:**  
`config/default.json` has `"mode": "react_tot"` and several mode values are referenced in the long-term engineering plan.  
The actual `gateway/reasoning_service.py` may or may not enforce that only `react_tot` is functional.

**Impact on docs:**  
If a user sets `REASONING__MODE=deep` and the system silently accepts it without doing anything different, the docs are misleading.

**Action required:**  
Review `reasoning_service.py` and either document exactly which modes are functional, or add a validation error for unsupported values.

---

## 5. 🟠 `skills/` directory structure and `SkillRegistry` loading path not fully verified

**What's missing:**  
`docs/architecture/skill-layer.md` and `CHANGELOG.md` reference `skills/packs/official/coding_copilot/` as an existing scaffold.  
The playbook `how-to-add-a-skill.md` references `skills/registry.py` and `OFFICIAL_PACKS`.  
These files need to be confirmed as existing and loadable.

**Impact on docs:**  
The skill playbook would fail for any reader who follows it if the registry or official pack structure doesn't match what's documented.

**Action required:**  
Confirm the actual paths and registry structure. Update `how-to-add-a-skill.md` to match reality.

---

## 6. 🟠 Channel adapters: `TelegramAdapter` exists but bot token config is not documented

**What's missing:**  
`channels/adapters/telegram_adapter.py` exists. However, nowhere in the configuration docs is it explained how to set the Telegram bot token, configure the webhook URL, or enable the Telegram channel.

**Impact on docs:**  
Users interested in Telegram deployment have no path to follow.

**Action required:**  
Add a section to `docs/configuration.md` (or a separate `docs/channels/telegram.md`) documenting:
- `TELEGRAM__BOT_TOKEN`
- `TELEGRAM__WEBHOOK_URL` (or polling mode)
- How to enable the channel

---

## 7. 🟠 Web UI exists (`UI/index.html`) but is not documented

**What's missing:**  
There is a built-in Web UI that opens automatically on startup.  
Its features, limitations, and configuration (e.g., does it support all API features or only a subset?) are nowhere documented.

**Impact on docs:**  
README and quickstart say "visit the Web UI" but don't explain what you can do with it or what is unsupported.

**Action required:**  
Add a brief `docs/ui-overview.md` covering: chat, session management, memory inspector (if exposed), tool panel (if exposed), known limitations.

---

## 8. 🟡 `example.env` references `API__FAILOVER_MODELS` but fallback logic is not confirmed

**What's missing:**  
The `failover_models` field exists in `config/default.json` and is set in `example.env`.  
It is unclear whether the runtime actually uses this list to retry failed calls or if it is a placeholder for future work.

**Impact on docs:**  
If the failover is not implemented, the docs are misleading (users might rely on it for production resilience).

**Action required:**  
Check `gateway/conversation_service.py` or wherever LLM calls are made for failover logic.  
If not implemented: mark `API__FAILOVER_MODELS` as "reserved for future use" in `docs/configuration.md`.

---

## 9. 🟡 `SANDBOX__PROFILE=strict` is documented but the enforcement difference from `dev` is not specified

**What's missing:**  
`sandbox.profile` has values `off`, `dev`, `strict` in `config/default.json`, but the behavioral difference between `dev` and `strict` is not documented anywhere.

**Action required:**  
In `docs/configuration.md` (sandbox section), specify exactly what each profile enables/disables.

---

## 10. 🟡 `GET /api/health/memory` endpoint referenced in playbook but may not exist

**What's missing:**  
`docs/playbooks/how-to-change-memory-backend.md` references:
```bash
curl "http://127.0.0.1:8000/api/health/memory"
```
This endpoint may not be implemented.

**Action required:**  
Implement it or remove the reference from the playbook.

---

## Summary table

| # | Description | Severity | Action |
|---|---|---|---|
| 1 | `plan_and_save` route may not exist | 🔴 | Verify or replace demo endpoint |
| 2 | Memory backend cold-start failure mode | 🔴 | Document + add health endpoint |
| 3 | MemoryWriteGate call path not verified | 🔴 | Trace and confirm |
| 4 | Reasoning modes not all functional | 🟠 | Document or validate |
| 5 | Skills registry path not confirmed | 🟠 | Confirm and update playbook |
| 6 | Telegram configuration not documented | 🟠 | Add channel config docs |
| 7 | Web UI not documented | 🟠 | Add ui-overview.md |
| 8 | Failover models may not be implemented | 🟡 | Verify or mark as future |
| 9 | Sandbox profile behavior not specified | 🟡 | Specify in config reference |
| 10 | `/api/health/memory` endpoint may not exist | 🟡 | Implement or remove reference |
