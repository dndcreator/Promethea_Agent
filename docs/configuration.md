# Configuration Reference

Promethea uses a three-layer configuration system with a clear priority order:

```
Sensitive runtime config (.env / user secrets.env)
Basic config (config/default.json / user config.json)
Advanced config (folded sections in config/default.json / user config.json)
```

Sensitive config and JSON config are intentionally separate. API credentials,
provider routing, model names, memory backend routing, and Neo4j credentials live
in env files. User-facing behavior parameters such as temperature, max tokens,
persona, reasoning limits, and memory thresholds live in JSON config.

All environment variable names use `__` as a nested delimiter:
`MEMORY__NEO4J__PASSWORD` -> `config.memory.neo4j.password`

Per-user layout:

```text
.env                                 # root default sensitive config
config/default.json                  # root default basic/advanced config
config/users/<user_id>/secrets.env   # user sensitive config, copied from root .env when missing
config/users/<user_id>/config.json   # user basic/advanced config, copied from default config
```

Existing user files are never overwritten by startup or registration helpers.

---

## Quick setup

```bash
cp env.example .env
# Edit sensitive runtime values (minimum: API__API_KEY, API__BASE_URL, API__MODEL)
python start_gateway_service.py
```

---

## Sensitive section: LLM runtime (`.env` / `secrets.env`)

Controls every LLM call made by the runtime.

| Environment variable | Type | Default | Notes |
|---|---|---|---|
| `API__API_KEY` | string | `placeholder-key-not-set` | **Required.** Your provider's secret key. |
| `API__BASE_URL` | string | _(empty)_ | **Required.** Must match your provider. |
| `API__MODEL` | string | _(empty)_ | **Required.** Must be a model your provider supports. |
| `API__FAILOVER_MODELS` | comma-separated string | `[]` | Optional fallback models on the main provider endpoint. |

### Multimodal model routing

Image input remains part of the Conversation model I/O path; it is not an
official tool and does not pass through tool routing. Promethea sends an image
request to the main model first. If the provider explicitly reports that the
model does not support the requested modality, the runtime remembers that
capability result for the process lifetime and uses the configured multimodal
model. Transport failures are not treated as capability failures.

| Environment variable | Type | Default | Notes |
|---|---|---|---|
| `MULTIMODAL__MODEL` | string | _(empty)_ | Optional dedicated image-capable model. |
| `MULTIMODAL__BASE_URL` | URL | _(empty)_ | Empty values inherit `API__BASE_URL`. |
| `MULTIMODAL__API_KEY` | string | _(empty)_ | Empty values inherit `API__API_KEY`. |

If no dedicated model is configured and the main model rejects image input,
Promethea removes the binary image part and retries with the existing caption
or OCR fallback. Audio transcription and speech generation continue to use the
separate Voice provider settings.

### Provider examples

**OpenRouter**
```bash
API__API_KEY=sk-or-...
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=openai/gpt-4.1-mini
```

**OpenAI**
```bash
API__API_KEY=sk-...
API__BASE_URL=https://api.openai.com/v1
API__MODEL=gpt-4.1-mini
```

**Local model (vLLM / Ollama / any OpenAI-compatible server)**
```bash
API__API_KEY=dummy-key   # arbitrary; some servers ignore it
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=local-llama-3-8b
```

**Azure OpenAI**
```bash
API__API_KEY=your-azure-key
API__BASE_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
API__MODEL=gpt-4o
```

> Warning: `API__BASE_URL` and `API__MODEL` are **coupled**. Configure them together for the same provider. Promethea treats provider/model as sensitive runtime routing, not normal JSON config.

When a user account is created, Promethea creates `config/users/<user_id>/secrets.env`
from the root `.env` only if that user file does not already exist. Users can then
edit their own `secrets.env` from the UI or manually. Secret values are never
returned in full by the API; the UI only shows configured/missing status.

---

## Basic section: `api` behavior (`config.json`)

These are non-sensitive behavior parameters and can live in `config/default.json`
or `config/users/<user_id>/config.json`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `api.temperature` | float 0-2 | `0.7` | Generation temperature. |
| `api.max_tokens` | int 1-8192 | `2000` | Max tokens per completion. |
| `api.max_history_rounds` | int 1-100 | `10` | Conversation turns kept in context. |
| `api.timeout` | int 1-300 | `null` | Request timeout in seconds. |
| `api.retry_count` | int 0-10 | `null` | Retry attempts on failure. |

---

## Sensitive section: web search provider (`.env` / `secrets.env`)

`web.search` is a stable official tool. The provider is selected at runtime from
the current user's secret settings, so the router and prompt only need to reason
about one web-search capability.

Search provider settings follow the same env-only mechanism as model routing and
Neo4j credentials. They must not be stored in `config/default.json` or
`config/users/<user_id>/config.json`.

Resolution order:

1. `config/users/<user_id>/secrets.env`
2. root `.env`
3. process environment variables

The Settings UI writes these values through `/api/config/secrets`. Existing
secret values are never returned in full; blank fields mean "keep the existing
value".

| Variable | Type | Default | Notes |
|---|---|---|---|
| `SEARCH__PROVIDER` | enum | `auto` | `auto` \| `brave` \| `tavily` \| `serpapi` \| `searxng` \| `duckduckgo` |
| `SEARCH__FALLBACK_POLICY` | enum | `fallback` | `fallback` tries eligible providers in order; `strict` does not switch after an execution failure. |
| `SEARCH__PROVIDER_ORDER` | comma-separated ids | `brave,tavily,serpapi,searxng,duckduckgo` | User-owned provider preference; unlisted providers follow declared priority. |
| `SEARCH__BRAVE_API_KEY` | string | _(empty)_ | Enables Brave Search when provider is `auto` or `brave`. |
| `SEARCH__TAVILY_API_KEY` | string | _(empty)_ | Enables Tavily when provider is `auto` or `tavily`. |
| `SEARCH__SERPAPI_API_KEY` | string | _(empty)_ | Enables SerpAPI when provider is `auto` or `serpapi`. |
| `SEARCH__SEARXNG_URL` | URL | _(empty)_ | Enables SearXNG when provider is `auto` or `searxng`. |

Provider selection:

1. If `SEARCH__PROVIDER` names a provider, Promethea selects that registered provider.
2. If it is `auto`, available providers follow `SEARCH__PROVIDER_ORDER`, then
   their provider-declared priority.
3. With `SEARCH__FALLBACK_POLICY=fallback`, failures advance through that set
   and may reach key-free DuckDuckGo. Results record the selected provider and
   whether fallback occurred.
4. With `SEARCH__FALLBACK_POLICY=strict`, Promethea does not silently switch
   providers after an execution failure.

Examples:

```bash
# Default: no key required, but less reliable.
SEARCH__PROVIDER=auto
SEARCH__FALLBACK_POLICY=fallback
SEARCH__PROVIDER_ORDER=brave,tavily,serpapi,searxng,duckduckgo

# Brave explicit provider.
SEARCH__PROVIDER=brave
SEARCH__BRAVE_API_KEY=your-brave-key

# Self-hosted SearXNG.
SEARCH__PROVIDER=searxng
SEARCH__SEARXNG_URL=http://127.0.0.1:8888
```

Provider implementation rule:

- The official tool remains `web.search`.
- Provider-specific code belongs in the web-search runtime/provider layer.
- Providers register by stable id; selection does not depend on import or
  registration order.
- Do not register separate official tools such as `brave.search` or
  `tavily.search` for the same general web-search capability.
- Additional providers should return the normalized result shape:
  `{query, provider, count, results: [{title, url, snippet, source}]}`.

---

## Sensitive section: memory backend (`.env` / `secrets.env`)

| Variable | Type | Default | Notes |
|---|---|---|---|
| `MEMORY__ENABLED` | bool | `true` | Master switch. Set to `false` to disable long-term memory. |
| `MEMORY__STORE_BACKEND` | enum | `neo4j` | `neo4j` \| `sqlite_graph` \| `flat_memory` |
| `MEMORY__SQLITE_GRAPH_PATH` | path | `memory/sqlite_graph.db` | File path for sqlite_graph backend. |
| `MEMORY__FLAT_MEMORY_PATH` | path | `memory/flat_memory.jsonl` | File path for flat_memory backend. |

### Backend comparison

| Backend | External service needed | Graph recall | Hot/warm/cold layers | Recommended for |
|---|---|---|---|---|
| `flat_memory` | No | No | No | Minimal degraded local run |
| `sqlite_graph` | No | Yes (recursive CTE) | No | Personal use or development when Neo4j is unavailable |
| `neo4j` | Yes (Neo4j >= 5) | Yes (Cypher) | Yes (full stack) | Production, multi-session |

### Cold-start behavior and health

Memory startup is fail-soft:

- If `MEMORY__ENABLED=false`, memory features stay disabled and the service still starts.
- If `MEMORY__STORE_BACKEND=neo4j` but Neo4j is unreachable, the service still starts, but memory is not ready.
- There is no automatic backend fallback from `neo4j` to `sqlite_graph` or `flat_memory`.

You can check effective runtime state via:

```bash
curl "http://127.0.0.1:8000/api/health/memory"
```

Key fields:
- `configured_backend`: backend from config
- `active_backend`: backend currently attached in memory adapter
- `ready`: whether memory is currently usable
- `reason`: why it is unavailable/degraded

### Neo4j connection

Only needed when `MEMORY__STORE_BACKEND=neo4j`.

| Variable | Default | Notes |
|---|---|---|
| `MEMORY__NEO4J__ENABLED` | `true` | Keep `true` for the default Neo4j path; set `false` when intentionally using another backend. |
| `MEMORY__NEO4J__URI` | `bolt://localhost:7687` | Neo4j bolt URI. |
| `MEMORY__NEO4J__USERNAME` | `neo4j` | Database username. |
| `MEMORY__NEO4J__PASSWORD` | _(empty)_ | Set this. Never commit it. |
| `MEMORY__NEO4J__DATABASE` | `neo4j` | Target database name. |
| `MEMORY__NEO4J__CONNECTION_TIMEOUT` | `3` | Seconds before connection times out. |

### Separate memory model (optional)

By default memory extraction uses the same API as the main model.  
To use a different, cheaper model for memory:

```bash
MEMORY__API__USE_MAIN_API=false
MEMORY__API__API_KEY=sk-your-memory-model-key
MEMORY__API__BASE_URL=https://openrouter.ai/api/v1
MEMORY__API__MODEL=google/gemma-3-27b-it:free
```

### Memory migration

To migrate data between backends without downtime:

```python
from memory.adapter import get_memory_adapter

adapter = get_memory_adapter()

# Phase 1: dual-write (writes go to both old and new backend)
adapter.configure_migration(
    mode="dual_write",
    source_backend="neo4j",
    target_backend="sqlite_graph",
)

# Phase 2: cut over (switch active backend to target)
result = adapter.migrate_backend("sqlite_graph", mode="cutover")
```

Or in one step (no dual-write period):

```python
result = adapter.migrate_backend("flat_memory", mode="cutover")
```

### Hippocampus replay

`memory.hippocampus` controls a durable background maintenance loop over memories
that have already passed the normal write gate. It is not another storage layer:
warm clustering, cold summarization, and forgetting retain their own configuration.

| Field | Default | Purpose |
|---|---:|---|
| `enabled` | `true` | Enable idle-time replay. |
| `state_path` | `memory/hippocampus/replay_state.json` | Restart-resumable checkpoint state; runtime data and ignored by Git. |
| `new_memory_threshold` | `24` | Run after this many newly accepted memories. |
| `min_interval_s` | `21600` | Minimum delay between completed cycles. |
| `max_interval_s` | `86400` | Process a smaller pending set after this maximum wait. |
| `revisit_interval_s` | `604800` | Revisit established memory even when no new threshold is reached. |
| `idle_delay_s` | `300` | Required quiet time after recent memory activity. |
| `poll_interval_s` | `30` | Scheduler wake interval. |
| `batch_size` | `24` | Maximum memories reflected on in one cycle. |
| `max_insights_per_cycle` | `4` | Maximum bounded writes or revisions per cycle. |
| `cognition_hint_threshold` | `4` | Queue replay after this many grounded temporary cognition hints accumulate. |
| `max_pending_cognition_hints` | `24` | Maximum bounded hints retained in the replay checkpoint state. |
| `max_cognition_hint_chars` | `2000` | Maximum normalized text retained per hint. |
| `retry_delay_s` | `300` | Delay before retrying a failed checkpoint. |

Adaptive or deep cognition that completed without degradation may offer its synthesis and
source memory IDs to replay. The synthesis is an untrusted hint, not evidence: replay must
re-read the referenced memories and every accepted insight must still cite a supplied
non-replay memory.

Replay yields to active conversation/task runs and memory synchronization. It
checkpoints before writes, resumes interrupted commits, and uses the configured
memory model through the existing Memory service. Restart the Runtime after
changing these project-level settings.

### Self Model cognitive recall

`self_model.recall` controls query-conditioned cognition over a single shared
candidate pool supplied by MemoryService. Passive Self Model projection remains
deterministic. The bounded reducer is invoked only through `cognition.recall` and
uses the configured memory model when Adaptive or Deep mode needs an LLM.

| Field | Default | Purpose |
|---|---:|---|
| `enabled` | `true` | Enable active cognition reduction. Disabled mode returns a Fast snapshot. |
| `candidate_pool_limit` | `60` | Maximum governed memory candidates requested once per recall. |
| `fast_candidate_limit` | `12` | Candidate ceiling for the no-extra-LLM path. |
| `fast_input_chars` | `6000` | Character budget for automatic Fast selection. |
| `deep_candidate_threshold` | `36` | Candidate count at which automatic mode may use Deep reduction. |
| `max_channels` | `3` | Maximum decomposition kernels. |
| `max_depth` | `2` | Maximum hierarchical reduction depth. |
| `max_parallel_calls` | `4` | Maximum concurrent kernel calls. |
| `max_kernel_calls` | `8` | Hard per-recall model-call budget. |
| `kernel_input_chars` | `16000` | Input budget for one kernel receptive field. |
| `max_skip_chars` | `5000` | Raw critical-memory residual budget. |
| `skip_score_threshold` | `0.82` | Score threshold for non-governance-critical skip items. |
| `deadline_ms` | `6000` | Hard active-recall deadline before deterministic degradation. |

All fields use the existing nested environment convention, for example
`SELF_MODEL__RECALL__MAX_CHANNELS=2`. Cognition snapshots are Run-scoped and are
not persisted by the reducer.

---

## Section: `sandbox` - Security policy

| Variable | Default | Notes |
|---|---|---|
| `SANDBOX__ENABLED` | `true` | Enable sandbox enforcement. |
| `SANDBOX__PROFILE` | `strict` | `off` \| `dev` \| `strict` |
| `SANDBOX__WORKSPACE_ACCESS` | `rw` | `rw` \| `ro` \| `none` |
| `SANDBOX__COMMAND_MODE` | `approval` | `deny` \| `approval` \| `allowlist` \| `audit` |
| `SANDBOX__DESKTOP_MODE` | `approval` | `observe_only` \| `approval` \| `host_control` |
| `SANDBOX__PROCESS_MODE` | `managed_only` | `managed_only` \| `host_control` |
| `SANDBOX__BROWSER_DISABLE_CHROMIUM_SANDBOX` | `false` | Emergency compatibility switch; weakens browser isolation. |
| `SANDBOX__COMPUTER_MAX_WORKSPACES` | `8` | Maximum cached computer workspaces (1-64); idle workspaces are evicted first. |
| `SANDBOX__NETWORK_MODE` | `restricted` | `restricted` \| `none` |
| `SANDBOX__BLOCK_PRIVATE_NETWORK` | `true` | Block access to `192.168.x`, `10.x`, `172.16-31.x`. |

`SANDBOX__PROFILE` currently acts as an operator label (`off`/`dev`/`strict`) and validation field.
It does not automatically override `workspace_access`, `command_mode`, or `network_mode`.
Set those fields explicitly for deterministic behavior.

The default permits workspace-scoped work while requiring a one-shot user
confirmation for command execution and host desktop input. Confirmation is
bound to the reviewed tool name and arguments, is consumed by that invocation,
and cannot override explicit `deny`, `observe_only`, or workspace boundaries.
Process termination remains limited to children tracked by the runtime.

The filesystem tool can read from the advertised Desktop, Documents, and
Downloads locations (including files selected by an absolute path beneath
those locations). These host locations are read-only: writes, appends, moves,
deletes, and directory creation remain confined to the workspace. Copying a
single host file into the workspace is allowed; recursively copying a host
directory is not. The Home and temporary locations are not general read grants.
Reading files does not grant mouse or keyboard control of the desktop.

Runtime tool calls and Gateway computer requests resolve computer controllers
from the authenticated user and workspace, using the same `WorkspaceService`
as official file and command tools. Browser storage and managed processes are
owned by that workspace. Idle controller sets can be evicted; active operations
and running managed processes are never evicted to make room. Desktop input
still targets the shared host desktop and is not isolated by workspace ownership.
Process results report their actual `sandbox.backend` and `sandbox.enforcement`.
The Chromium process sandbox is explicitly enabled unless the compatibility
switch above is set; it does not isolate the entire desktop or external accounts.

Approved process tools use a platform provider: Linux requires `bwrap`, macOS
requires `sandbox-exec`, and Windows requires `pywin32` (installed with the
Windows Python dependency). `command_mode=allowlist` is an optional standing
operator policy and does not require per-call approval.
Windows runs native commands under a write-restricted token and a job object;
it does not require Docker. The workspace must be on an ACL-capable volume and
owned by the Runtime user. The first execution adds a persistent inheritable
write-capability ACE to that workspace, which may take time for large trees.
Runner startup failures fail closed. All providers receive a minimal environment
without Runtime credentials. The Linux and macOS providers
currently allow read access to host files outside the workspace, so they protect
against writes and network access but **not** against reading host secrets.
Windows reports `partial` enforcement: the restricted token limits file writes,
but caller-readable files, network access, and process visibility are not
isolated. Ambient Everyone grants and NTFS hard links may also permit writes
outside the selected path. `SANDBOX__NETWORK_MODE` governs the direct network
tools, not arbitrary network activity in a Windows subprocess. Missing providers
fail closed with `SANDBOX_UNAVAILABLE`; `workspace_access=ro` omits the explicit
workspace write grant but retains the same partial-enforcement caveats.
This process boundary does not confine Python code executing inside the Runtime
itself, third-party plugin internals, or PyAutoGUI's host desktop controls.

`host_control` is an explicit operator assertion, not an isolation mechanism.
Only enable it when Promethea itself is running inside a disposable VM, Windows
Sandbox, container-compatible desktop, or a dedicated low-privilege account.
User confirmation grants an action; it does not make the host environment safe.

**Recommended settings per environment:**

| Environment | Profile | Notes |
|---|---|---|
| Local dev | `strict` | Default; host mutations require one-shot approval |
| Staging | `dev` | Catch issues before production |
| Production | `strict` | Prefer `deny` unless an interactive approval channel is available |

The compatibility command allowlist, used only when `command_mode=allowlist`, is:
`python`, `pytest`, `pip`, `uv`, `git`, `rg`, `cmd`, `powershell`. An allowlist is
not process isolation: interpreters and shells can still perform arbitrary host
effects. Use `command_mode=deny` when those partial boundaries are insufficient.

Denied command fragments (always active when sandbox is enabled):  
`rm -rf`, `del /f /q`, `format `, `shutdown`, `reboot`, `mkfs`, `diskpart`, `net user`, `reg add`.

---

## Section: `action` - Main-model control loop

`action.max_steps` bounds the number of tool actions the main model may take during one
turn. The default is `5`; per-user JSON configuration can lower or raise it without
changing routing code. Runtime validation keeps the value between `1` and `50`.

---

## Section: `reasoning` - Multi-step planning

Enabled by default in the public preview. It only starts a full reasoning tree when the runtime budget gate selects deep reasoning, but complex turns can still increase token usage.

| Variable | Default | Notes |
|---|---|---|
| `REASONING__ENABLED` | `true` | Enable reasoning tree support. |
| `REASONING__MODE` | `react_tot` | Currently only `react_tot` is supported. |
| `REASONING__MAX_DEPTH` | `4` | Maximum tree depth. |
| `REASONING__MAX_NODES` | `24` | Maximum nodes across the tree. |
| `REASONING__MAX_TOOL_CALLS` | `8` | Tool calls allowed per reasoning run. |
| `REASONING__MAX_MEMORY_CALLS` | `6` | Memory recalls allowed per reasoning run. |
| `REASONING__MAX_REPLAN_ROUNDS` | `6` | Per-node ReAct replanning iterations before moving on. |
| `REASONING__MAX_REACT_ROUNDS_TOTAL` | `14` | Global ReAct round budget across the whole tree. Preserves ReAct but prevents long multi-node runs from expanding indefinitely. |
| `REASONING__TARGET_RUNTIME_SECONDS` | `240` | Soft runtime target. After this, ReAct should prefer synthesis over new external actions unless the marginal value is clear. |
| `REASONING__MAX_RUNTIME_SECONDS` | `480` | Hard runtime ceiling for reasoning expansion. |
| `REASONING__MAX_LOW_YIELD_TOOL_FAILURES` | `4` | Low-yield tool-failure threshold. When repeated tool observations fail, ReAct should switch toward synthesis with uncertainty. |
| `REASONING__MOIRAI_EXPORT_PLAN` | `false` | Export plan to Moirai workflow storage. |

---

## Section: `system` - Runtime settings

| Variable | Default | Notes |
|---|---|---|
| `SYSTEM__LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `SYSTEM__LOG_MODEL_PAYLOADS` | `false` | Opt in to dependency debug logs that may contain prompts, conversations, or recalled memory. |
| `SYSTEM__DEBUG` | `false` | Enable extra debug output. |
| `SYSTEM__STREAM_MODE` | `true` | Stream responses when possible. |
| `SYSTEM__SESSION_TTL_HOURS` | `0` | Session expiry in hours. `0` = no expiry. |

---

## Channels (current state)

Channel runtime support is not symmetric.

- Telegram adapter exists, but full first-party bot runtime wiring is not yet a config-only turnkey flow.
- Do not assume `TELEGRAM__...` variables are active unless you implement corresponding runtime handlers.

See:

- `docs/channels/telegram.md`

---

## Section: `extensions` - official/community tool exposure

Promethea exposes all user-callable tools through a unified Extension Catalog:

- Official local tools are registered from `gateway/official_tools`.
- Built-in manifest packs under `agentkit/tools` are treated as official local tools.
- Community tools are dropped into `extensions/community/<extension_id>` with an
  `agent-manifest.json` file and can be hot-reloaded.
- External MCP manifests declare a stdio `transport` and remain out of process.

APIs:
- `GET /api/extensions/catalog`
- `POST /api/extensions/reload`

See `docs/extensions.md` for the manifest format and community extension rules.

---

## Section: `prompts` - System prompt

| Variable | Default |
|---|---|
| `PROMPTS__PROMETHEA_SYSTEM_PROMPT` | _(see `config.py`)_ |

Override the agent's system prompt via `.env` or `config/default.json`.

### Prompt assembly lifecycle

Promethea does not send this base prompt to the model by itself. Normal chat requests pass through `PromptAssembler`, which combines the base identity prompt with runtime blocks.

Before assembly, `ConversationService` reads the structured runtime tool catalog.
The main model then performs the first decision inside the normal control loop:
it can answer directly, recall memory, invoke a tool or workflow, or call the
deeper reasoning service. This avoids a separate Router LLM request while keeping
budgets, tool policy, permissions, and service ownership in deterministic runtime code.

The assembler is called by:
- `gateway.conversation_pipeline` for the canonical main-model control loop when messages are not already prebuilt.
- `gateway.conversation_service.prepare_chat_turn` for Web/streaming chat paths before the LLM call.

The assembler can include these blocks:
- `identity`: base Promethea identity plus language policy.
- `soul_core`: the read-mostly soul prompt, style/personality only.
- `memory`: personal context returned by the `memory.get_context` capability.
- `org_context`: organization context when enterprise brain is enabled.
- `reasoning`: explicit reasoning output returned by the `reasoning.run` capability.
- `skill`, `tools`, `workspace`, `policy`, `response_format`: active capability, workspace, policy, and output-style blocks.

Important separation:
- Behavior defaults such as `prompts`, `soul`, response style, and prompt block policy can be inherited by every user.
- Deployment/user-specific model settings such as provider, model name, API key, Neo4j password, and file paths should be configured explicitly through `.env` or the settings UI. Do not treat those as identity/persona defaults.

If a caller passes a fully prebuilt message list directly to the staged pipeline, the pipeline preserves it and marks `prompt_assembly.source=prebuilt_messages`. Use this only for controlled continuation/replay paths; normal user chat should go through `prepare_chat_turn` or the canonical staged pipeline.

---

## `config/default.json`

This file ships with the repository and contains project-level basic/advanced defaults.
It must not contain API keys, provider routing, model names, memory backend routing,
or Neo4j credentials.

New user accounts receive a copy of this JSON config. Sensitive runtime values are
copied separately from root `.env` into the user's `secrets.env`.

---

## Section: `persona.soul` (view-only + auto-evolve)

`persona.soul` is a style-only prompt block injected by the prompt assembler.
The key name is kept for backward compatibility with existing user config, but
runtime personality now flows through `soul_core`; separate `persona_core` and
`persona_module` prompt blocks are no longer injected.

Constraints:
- UI is read-only for this block by default.
- Runtime may evolve it automatically after turns.
- It cannot override policy/safety/tool/reasoning constraints.

Config shape:

```json
{
  "persona": {
    "soul": {
      "enabled": true,
      "read_only_in_ui": true,
      "auto_evolve": true,
      "content": "Soul Prompt...",
      "version": 1,
      "updated_at": "",
      "last_reason": "",
      "evolve_every_turns": 6,
      "min_interval_seconds": 900,
      "max_chars": 1200
    }
  }
}
```

APIs:
- `GET /api/config/soul`
- `GET /api/config` (response includes top-level `soul`)

---

## Section: `self_evolve` - capability evolution

`self_evolve` is an experimental, disabled-by-default module for append-only
capability packages. Tasks can write only inside their staging directory. A
validated package is published as an immutable version under
`extensions/community/_generated`, registered through the existing extension
registry, and executed outside the Gateway process by the process sandbox.
Validation must execute every declared command, and publication is bound to the
validated content digest. Tasks and generated commands are private to their
creating user. Self Evolve cannot edit Promethea Core files.

Self Evolve consumes the unified Self Model (`self`, user-scoped `cognition`,
`capabilities`, and `evolution`) but does not own cognition or memory persistence.
User cognition remains a runtime projection over the existing Memory service.

| Field | Default | Notes |
|---|---:|---|
| `self_evolve.enabled` | `false` | Enables the HTTP self-evolve endpoints for the current user. Keep disabled for normal accounts. |
| `self_evolve.max_tasks_list` | `50` | Maximum tasks returned by list endpoints. |
| `self_evolve.max_context_chars_per_file` | `4000` | Bounded file context returned for a staged package. |

APIs:
- `GET /api/self-evolve/status`
- `POST /api/self-evolve/tasks`
- `GET /api/self-evolve/tasks`
- `GET /api/self-evolve/tasks/{task_id}`
- `POST /api/self-evolve/tasks/{task_id}/context`
- `PUT /api/self-evolve/tasks/{task_id}/files`
- `POST /api/self-evolve/tasks/{task_id}/validate`
- `POST /api/self-evolve/tasks/{task_id}/publish`

---

## Time and scheduling

`system.timezone` defaults to `auto`. Runtime resolution prefers an explicit
user setting, then a client-provided IANA timezone, and finally the host
timezone. Values such as `Europe/Paris`, `UTC`, and `system` are valid. The
resolved timezone is included in model runtime context and stored with
calendar-based scheduled jobs.

Scheduled targets can be any registered capability. Supported trigger shapes:

```json
{"type": "interval", "seconds": 300}
{"type": "at", "at": "2026-10-01T09:00:00"}
{"type": "calendar", "time": "09:00", "weekdays": [0, 1, 2, 3, 4]}
```

Weekdays use Monday `0` through Sunday `6`. Naive `at` values are interpreted
in the job timezone; offset-aware values retain their stated instant.

---

## Section: `org_brain` (enterprise context module)

`org_brain` enables B-side organization context recall without affecting personal mode.

```json
{
  "org_brain": {
    "enabled": false,
    "org_id": "",
    "recall_priority": "blend",
    "confirmation_queue": true,
    "audience_default": "business_department"
  }
}
```

Fields:
- `enabled`: master switch.
- The Web UI hides enterprise upload/recall/graph entrypoints when this is `false`. After changing it, restart the service so runtime modules and prompt injection state are aligned.
- `org_id`: organization namespace id.
- `recall_priority`: `blend` or `override_persona`.
- `confirmation_queue`: reserve switch for human confirmation flow.
- `audience_default`: default audience when turn metadata does not specify one.
- `max_upload_bytes`: max file size accepted by `/api/org-brain/ingest-file`.
- `allowed_suffixes`: accepted file suffix list for upload ingest.
- `recall_top_k_default`: default `top_k` for recall API when omitted.
- `recall_context_type_default`: default `context_type` for recall API when omitted.
- `chat_top_k`: default top-k used by chat/runtime recall.
- `chat_context_type`: default context type used by chat/runtime recall.
- `summary_label` / `summary_max_items`: summary rendering behavior.
- `extract_text_max_chars`: max chars sent into extraction prompt.
- `heuristic_max_lines` / `heuristic_max_items`: fallback extraction limits.

API:
- `GET /api/org-brain/status`
- `POST /api/org-brain/ingest`
- `POST /api/org-brain/ingest-file` (upload file and auto-extract text before ingest)
- `POST /api/org-brain/recall`
