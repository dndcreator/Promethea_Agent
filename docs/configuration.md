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
| `API__FAILOVER_MODELS` | comma-separated string | `[]` | Advanced/reserved. Listed in config schema, but runtime model failover is not wired by default yet. |

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
| `SEARCH__BRAVE_API_KEY` | string | _(empty)_ | Enables Brave Search when provider is `auto` or `brave`. |
| `SEARCH__TAVILY_API_KEY` | string | _(empty)_ | Enables Tavily when provider is `auto` or `tavily`. |
| `SEARCH__SERPAPI_API_KEY` | string | _(empty)_ | Enables SerpAPI when provider is `auto` or `serpapi`. |
| `SEARCH__SEARXNG_URL` | URL | _(empty)_ | Enables SearXNG when provider is `auto` or `searxng`. |

Provider selection:

1. If `SEARCH__PROVIDER` names a provider, Promethea tries that provider first.
2. If it is `auto`, Promethea uses the first configured provider in this order:
   Brave, Tavily, SerpAPI, SearXNG.
3. If no configured provider works, Promethea falls back to DuckDuckGo HTML
   search. DuckDuckGo is key-free but less stable than API-backed providers.

Examples:

```bash
# Default: no key required, but less reliable.
SEARCH__PROVIDER=auto

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

---

## Section: `sandbox` - Security policy

| Variable | Default | Notes |
|---|---|---|
| `SANDBOX__ENABLED` | `false` | Enable sandbox enforcement. |
| `SANDBOX__PROFILE` | `off` | `off` \| `dev` \| `strict` |
| `SANDBOX__WORKSPACE_ACCESS` | `rw` | `rw` \| `ro` \| `none` |
| `SANDBOX__COMMAND_MODE` | `allowlist` | `allowlist` \| `audit` |
| `SANDBOX__NETWORK_MODE` | `restricted` | `restricted` \| `none` |
| `SANDBOX__BLOCK_PRIVATE_NETWORK` | `true` | Block access to `192.168.x`, `10.x`, `172.16-31.x`. |

`SANDBOX__PROFILE` currently acts as an operator label (`off`/`dev`/`strict`) and validation field.
It does not automatically override `workspace_access`, `command_mode`, or `network_mode`.
Set those fields explicitly for deterministic behavior.

**Recommended settings per environment:**

| Environment | Profile | Notes |
|---|---|---|
| Local dev | `off` or `dev` | Convenience over strictness |
| Staging | `dev` | Catch issues before production |
| Production | `strict` | Command allowlist active, network restricted |

The default command allowlist (`dev` profile): `python`, `pytest`, `pip`, `uv`, `git`, `rg`, `cmd`, `powershell`.

Denied command fragments (always active when sandbox is enabled):  
`rm -rf`, `del /f /q`, `format `, `shutdown`, `reboot`, `mkfs`, `diskpart`, `net user`, `reg add`.

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
- Built-in MCP manifest packs under `agentkit/tools` are treated as official.
- Community tools are dropped into `extensions/community/<extension_id>` with an
  `agent-manifest.json` file and can be hot-reloaded.

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

Before assembly, `PromptPolicyRouter` runs a lightweight first pass. It asks the
model for strict JSON describing which dynamic blocks look useful for this turn.
The router can suggest memory, reasoning, tools, workspace, and org context. It
cannot disable or rewrite required blocks such as identity, soul core, or
safety/policy constraints.

The router is LLM-driven. It does not use keyword lists or deterministic
language-specific memory hints. If the router output is unavailable or invalid,
Promethea falls back to a neutral default and lets the normal memory recall
classifier decide whether long-term context is needed.

The assembler is called by:
- `gateway.conversation_pipeline.stage_response_synthesis` for the canonical staged pipeline when messages are not already prebuilt.
- `gateway.conversation_service.prepare_chat_turn` for Web/streaming chat paths before the LLM call.

The assembler can include these blocks:
- `identity`: base Promethea identity plus language policy.
- `soul_core`: the read-mostly soul prompt, style/personality only.
- `memory`: recalled personal memory context.
- `org_context`: organization context when enterprise brain is enabled.
- `reasoning`: explicit reasoning summary when the reasoning engine rewrites or augments the prompt.
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

## Section: `self_evolve` - controlled code evolution

`self_evolve` is an experimental, disabled-by-default module for scoped code
evolution tasks. It is not general autonomous self-modification: every task must
declare target files, patches are limited to those files, and validation commands
are checked by sandbox policy.

| Field | Default | Notes |
|---|---:|---|
| `self_evolve.enabled` | `false` | Enables the HTTP self-evolve endpoints for the current user. Keep disabled for normal accounts. |
| `self_evolve.max_tasks_list` | `50` | Maximum tasks returned by list endpoints. |
| `self_evolve.max_context_chars_per_file` | `4000` | Bounded file context per target file. |
| `self_evolve.max_validate_timeout_seconds` | `180` | Maximum validation command timeout. |

APIs:
- `GET /api/self-evolve/status`
- `POST /api/self-evolve/tasks`
- `GET /api/self-evolve/tasks`
- `GET /api/self-evolve/tasks/{task_id}`
- `POST /api/self-evolve/tasks/{task_id}/context`
- `POST /api/self-evolve/tasks/{task_id}/patch`
- `POST /api/self-evolve/tasks/{task_id}/validate`

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
