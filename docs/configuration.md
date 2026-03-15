# Configuration Reference

Promethea uses a three-layer configuration system with a clear priority order:

```
Environment variables / .env    ← highest priority
config/default.json             ← project-level defaults
Code defaults (PrometheaConfig) ← fallback
```

All environment variable names use `__` as a nested delimiter:  
`MEMORY__NEO4J__PASSWORD` → `config.memory.neo4j.password`

---

## Quick setup

```bash
cp example.env .env
# Edit .env: set API__API_KEY, API__BASE_URL, API__MODEL
python start_gateway_service.py
```

---

## Section: `api` — Main model

Controls every LLM call made by the runtime.

| Environment variable | Type | Default | Notes |
|---|---|---|---|
| `API__API_KEY` | string | `placeholder-key-not-set` | **Required.** Your provider's secret key. |
| `API__BASE_URL` | string | `https://openrouter.ai/api/v1` | **Must match your provider.** |
| `API__MODEL` | string | `nvidia/nemotron-3-nano-30b-a3b:free` | **Must be a model your provider supports.** |
| `API__TEMPERATURE` | float 0–2 | `0.7` | Generation temperature. |
| `API__MAX_TOKENS` | int 1–8192 | `2000` | Max tokens per completion. |
| `API__MAX_HISTORY_ROUNDS` | int 1–100 | `10` | Conversation turns kept in context. |
| `API__TIMEOUT` | int 1–300 | `null` | Request timeout in seconds. |
| `API__RETRY_COUNT` | int 0–10 | `null` | Retry attempts on failure. |
| `API__FAILOVER_MODELS` | comma-separated string | `[]` | Models tried in order if primary fails. |

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

> ⚠️ `API__BASE_URL` and `API__MODEL` are **coupled**. Changing only `API__API_KEY` and keeping the default `BASE_URL` pointing at OpenRouter while setting an OpenAI model name will fail.

---

## Section: `memory` — Memory system

| Variable | Type | Default | Notes |
|---|---|---|---|
| `MEMORY__ENABLED` | bool | `false` | Master switch. Set to `true` to enable long-term memory. |
| `MEMORY__STORE_BACKEND` | enum | `neo4j` | `neo4j` \| `sqlite_graph` \| `flat_memory` |
| `MEMORY__SQLITE_GRAPH_PATH` | path | `memory/sqlite_graph.db` | File path for sqlite_graph backend. |
| `MEMORY__FLAT_MEMORY_PATH` | path | `memory/flat_memory.jsonl` | File path for flat_memory backend. |

### Backend comparison

| Backend | External service needed | Graph recall | Hot/warm/cold layers | Recommended for |
|---|---|---|---|---|
| `flat_memory` | No | No | No | First-time users, minimal setup |
| `sqlite_graph` | No | Yes (recursive CTE) | No | Personal use, development |
| `neo4j` | Yes (Neo4j ≥ 5) | Yes (Cypher) | Yes (full stack) | Production, multi-session |

### Neo4j connection

Only needed when `MEMORY__STORE_BACKEND=neo4j`.

| Variable | Default | Notes |
|---|---|---|
| `MEMORY__NEO4J__ENABLED` | `false` | Must set to `true` explicitly. |
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

## Section: `sandbox` — Security policy

| Variable | Default | Notes |
|---|---|---|
| `SANDBOX__ENABLED` | `false` | Enable sandbox enforcement. |
| `SANDBOX__PROFILE` | `off` | `off` \| `dev` \| `strict` |
| `SANDBOX__WORKSPACE_ACCESS` | `rw` | `rw` \| `ro` \| `none` |
| `SANDBOX__COMMAND_MODE` | `allowlist` | `allowlist` \| `audit` |
| `SANDBOX__NETWORK_MODE` | `restricted` | `restricted` \| `none` |
| `SANDBOX__BLOCK_PRIVATE_NETWORK` | `true` | Block access to `192.168.x`, `10.x`, `172.16–31.x`. |

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

## Section: `reasoning` — Multi-step planning

Disabled by default. Enabling this increases token usage significantly.

| Variable | Default | Notes |
|---|---|---|
| `REASONING__ENABLED` | `false` | Enable reasoning tree. |
| `REASONING__MODE` | `react_tot` | Currently only `react_tot` is supported. |
| `REASONING__MAX_DEPTH` | `4` | Maximum tree depth. |
| `REASONING__MAX_NODES` | `24` | Maximum nodes across the tree. |
| `REASONING__MAX_TOOL_CALLS` | `4` | Tool calls allowed per reasoning run. |
| `REASONING__MAX_MEMORY_CALLS` | `4` | Memory recalls allowed per reasoning run. |
| `REASONING__MAX_REPLAN_ROUNDS` | `3` | Replanning iterations before giving up. |
| `REASONING__MOIRAI_EXPORT_PLAN` | `false` | Export plan to Moirai workflow storage. |

---

## Section: `system` — Runtime settings

| Variable | Default | Notes |
|---|---|---|
| `SYSTEM__LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `SYSTEM__DEBUG` | `false` | Enable extra debug output. |
| `SYSTEM__STREAM_MODE` | `true` | Stream responses when possible. |
| `SYSTEM__SESSION_TTL_HOURS` | `0` | Session expiry in hours. `0` = no expiry. |

---

## Section: `prompts` — System prompt

| Variable | Default |
|---|---|
| `PROMPTS__PROMETHEA_SYSTEM_PROMPT` | _(see `config.py`)_ |

Override the agent's system prompt via `.env` or `config/default.json`.

---

## Full example `.env`

See `example.env` for a complete, commented example covering all four API provider options and all backend choices.

---

## `config/default.json`

This file ships with the repository and contains the project-level defaults (no secrets).  
It is loaded after code defaults but before `.env`.

To override defaults without editing the file, use `.env` or environment variables.  
Do not commit secrets to `config/default.json`.
