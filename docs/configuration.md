# Configuration Reference

## Model Cost Estimates

The old fixed example tariff is removed. Runtime metrics use the actual returned
usage and a quote selected by **exact base URL and requested model**. Prices never
control Agent choices or permissions. Missing/invalid pricing, missing required
cache-token breakdown, or missing usage stays unknown; zero is reserved for an
explicit zero rate. Multimodal requests are not priced with a text-only tariff.

Operator settings follow root `.env` and explicit environment overrides:

```dotenv
PRICING__AUTO_REFRESH=true
PRICING__CACHE_TTL_S=3600
PRICING__REQUEST_TIMEOUT_S=2
PRICING__RATES=[]
```

The automatic source currently implemented is the official
[OpenRouter model catalog](https://openrouter.ai/api/v1/models), and only for
requests sent to `https://openrouter.ai/api/v1`. This is a catalog-based estimate,
not a routed-provider invoice. Do not reuse its price for a direct DeepSeek,
OpenAI-compatible proxy, or a different endpoint with the same model name.
Scheduled overrides and non-token charges are deliberately left unpriced rather
than silently ignored. Other direct providers currently need configured rates.

The first matching call refreshes the in-memory cache, at most once per TTL;
simultaneous requests share a bounded refresh. Only the public catalog is fetched,
without model credentials, redirects, proxy inheritance or LLM calls. A failed
refresh is throttled and expired quotes become unknown. Cold refresh may add up
to the configured timeout; unsupported providers make no pricing network request.

`PRICING__RATES` is a JSON list. Each record specifies `base_url`, `model`,
`input_per_million`, `output_per_million`, and optionally
`cache_read_per_million`. Amounts are non-negative **USD per million tokens**,
supplied from the operator's actual tariff; there are no default rate examples.
Base URLs cannot contain credentials, queries or fragments. Duplicate
endpoint/model pairs are rejected. Configured rates take precedence over catalog
estimates. Restart after changing deployment pricing. Local-model pricing is
unknown unless the operator explicitly configures a tariff; do not assume the
machine's running cost is zero.

Each priced model response retains its quote source, retrieval time and revision.
Action model-call manifests record that cost snapshot in the existing Runtime
Event Log. Cache refreshes cannot reprice past calls. The Metrics panel remains
process-lifetime aggregate telemetry, not a persistent account billing ledger:
its total is unknown if any recorded call is unpriced; the API separately exposes
`known_estimated_usd`, `priced_calls` and `unpriced_calls` for coverage. Rebooting
resets those aggregates. The provider's actual bill remains authoritative.

## Ambient Collaboration

`AmbientService` is a first-level, in-process service. Its deployment switch is
`AMBIENT__ENABLED=true`; each personal space remains **off until explicitly enabled**
in Workbench / Work. The optional focus can be empty: relevance and the next
action are model decisions, not a domain-specific rule table.

Deployment ceilings follow the existing nested environment convention:
`AMBIENT__INTERVAL_S=3600`, `AMBIENT__COOLDOWN_S=30`,
`AMBIENT__DAILY_CYCLES=24`, `AMBIENT__MAX_PARALLEL=1`,
`AMBIENT__MAX_STEPS=5`, `AMBIENT__MAX_TOKENS=2048`,
`AMBIENT__TIMEOUT_S=120`, `AMBIENT__COMMUNICATION_COOLDOWN_S=30`.
Daily cycles are per account, using UTC calendar days.
Tokens are capped per provider response, not an exact daily billing allowance;
delegation also remains subject to the existing multi-agent ceilings.

Runtime events and periodic checks trigger bounded activations of the same
personal-space situation across conversations. Foreground turns take admission priority. Only the running
server can do work: stopping the process stops computation, while durable
attention, Task checkpoints, annotations and feedback survive a restart.
External applications are not implicitly monitored.

Readonly investigation and owned-workspace work use existing tool policies.
Sensitive effects wait for exact one-call approval. Disabling or changing the
focus revokes the execution scope; uncertain interrupted effects are observations
on recovery, never blindly replayed. Working interpretations are not automatically
written as Memory facts. Personal archive transfer includes this state but does
not transfer autonomy permission: imported situations start disabled.

Self Model projects owned memory, tasks, workflows, recent conversations, working
attention and communication receipts for every root entrypoint. Greetings use the
same identity, customization and Soul blocks while retaining their own concise
presentation. They generate only on an actual welcome visit/language change or
long-idle return; the same visit receipt is idempotent. An offered greeting does
not imply that the user read it.

Existing AgentMessages IPC coordinates root notifications across conversations.
Root action turns share the personal identity lock; independent children and
read-only greeting preparation may progress concurrently. Communication receipts
live in Runtime Event Log, duplicate notices are suppressed, and cooldown deferrals
retain their original Task outbox/checkpoint for later consideration. Notices do
not count as new user interactions. Autonomous schedules inherit revocable origin
authority; explicitly user-created schedules remain independent.

The SDK exposes `client.ambient.get/configure/feedback/confirm`; `/api/ambient`
reads/configures the personal scope, while session-qualified routes select an owned
communication channel without creating a second cognitive identity. Public types
are generated from `gateway/public_contracts.py`. See
[Runtime ownership](architecture/task-runtime.md#ambient-service) for the boundaries.

## SelfModel And Semantic UI

SelfModel's working cognition and Semantic UI expression state live under
`.runtime/self-model/`, separate from Memory backend selection and Ambient
permission. Legacy Ambient attention is migrated once on startup. Personal-space
bundles include this state, but importing never enables autonomous work and never
restores a claim about the user's currently visible view. Account deletion removes
the corresponding state. These files are local Runtime data and are ignored by Git.

Semantic UI has no arbitrary-tool bridge. Authenticated clients can read expressions
and send declared feedback through `client.semanticUI`; the host reports bounded
view IDs and owned object references, not guessed intentions. Environment leases
are memory-only, expire after `SELF_MODEL__ENVIRONMENT_TTL_S` (default 60 seconds,
20-300), and reset on restart/import. A 20-second client heartbeat renews freshness
without producing an event or model request when the descriptor is unchanged.
Hidden/closed surfaces are excluded immediately when the report arrives.
`SELF_MODEL__OBSERVATION_CHARS` (default 3200, 1200-12000) reserves a separate,
non-compactable model-visible JSON projection; large details are explicitly omitted
and remain available through `environment.inspect`. Source reads are bounded and
unavailable sources stay unavailable, never inferred as facts. There is no new
perception LLM or background watcher. Proactive execution remains Ambient opt-in.
Keep the existing Canvas bridge restricted when embedding custom applications. See
[Semantic expressions](architecture/intelligent-canvas.md#semantic-expressions-are-separate).

## Optional Multi-Agent Delegation

The chat composer has a **Multi-agent** switch for authenticated users. It is off
initially; enabling it allows the main model to choose bounded delegation. It does
not force every request into multiple agents. Clients use the existing RunRequest
extension field `metadata.multi_agent: true`; HTTP/SSE and Gateway WebSocket keep
the same conversation execution path. Guest chat never enters this path.

Deployment configuration follows the existing nested environment mechanism:

```dotenv
MULTI_AGENT__ENABLED=true
MULTI_AGENT__MAX_CHILDREN=6
MULTI_AGENT__MAX_PARALLEL=3
MULTI_AGENT__MAX_PENDING=24
MULTI_AGENT__MAX_DEPTH=1
MULTI_AGENT__CHILD_STEPS=5
MULTI_AGENT__CHILD_MAX_TOKENS=2048
MULTI_AGENT__TIMEOUT_S=120
MULTI_AGENT__RESULT_CHARS=12000
```

Deployment limits are ceilings; user `multi_agent` overrides can only narrow
them. `max_children` counts admissions across the parent action and confirmation
continuations, `max_parallel` also caps active children in this Runtime process,
and depth is enforced at each delegation. Foreground work returns a blocker when
capacity is occupied; durable background work waits in its persisted inbox.

`subagent.delegate` is a normal manifest-discovered tool. Its `objective` must
include the needed context, `label` identifies the work, and optional `tools`
selects exact canonical tool names (`[]` gives no tools). `run_in_background`
defaults to `true`: acceptance returns a durable `child_id` and message `run_id`
without waiting for execution. Set it to `false` for foreground one-shot collection.
Independent delegations can use the canonical `tool_calls` action's `calls` array.
Children get fresh message/action state and share the parent's owned workspace,
model configuration and sandbox restrictions; they are not separate OS sandboxes
or isolated filesystem copies. Tool access can only narrow the parent's available
catalog. Permission-requiring actions are blocked in children and returned to the
parent to handle through the normal confirmation path.

The design follows the local DeepSeek Harness `subagent-spawn-in-process`,
`subagent-in-process-driver`, and `tool-subagent` ownership/isolation principles.
It uses Promethea's existing ConversationService/ActionService rather than their
implementation or a separate agent loop. Child events and model manifests retain
parent action lineage in the existing Runtime log. Child model replies are not
published as user turns or automatically extracted into personal memory; the
parent receives their observations and produces the user-facing reply. Foreground
child usage is included in parent totals; background usage belongs to its own
Task run and model-call records. Cancelled/infrastructure-interrupted
children may have incomplete provider usage, which remains visible in model-call
events where supplied by the provider.

Persistent child identity is owned by a durable Task, not a second session manager.
Each accepted message is one Task run; TaskRuntime owns leases, heartbeats, FIFO
activation, pause/resume/cancel and restart adoption. A completed message leaves
the child ready for follow-ups, rather than permanently closing it. The process
must be running to do work: shutdown preserves the inbox and durable Runtime
state, not a live model connection. `max_pending` bounds admitted active/queued
children per user; queued messages per child are also bounded.

`subagent.control` supports `list`, `get`, `send`, `interrupt`, `resume` and `cancel`.
Only the owning direct parent can address a child; account ownership alone does
not authorize a different conversation or a sibling agent. Sending during work
enqueues a later FIFO turn, not an edit of the active prompt. `interrupt` maps to
the existing Task pause semantics, including queued turns; `resume` continues
them, while `cancel` permanently closes the child. Existing Task UI controls are
also available, and delegation cards link directly to that Task's Workbench.

Action checkpoints retain messages, Observations, model steps and completed
results. On restart, a tool call whose outcome was not checkpointed is never
automatically dispatched again: Runtime supplies `TOOL_OUTCOME_UNKNOWN` and lets
the agent inspect state and replan. This is not an exactly-once guarantee for
external effects. Failed, cancelled and timed-out work stays traceable.

### Parent/Child Communication

Agent communication is in-process message passing with durable records, not an
additional OS-process RPC server. Parent commands retain the existing per-child
FIFO: acceptance returns a stable `message_id` (the Task run ID), and subsequent
execution belongs to TaskRuntime rather than the originating HTTP request.

An executing persistent child may call `subagent.report` with `content` and
`delivery: "quiet" | "wakeup"`. Quiet reports wait for the parent's next model
step; waking reports also request an idle parent's continuation. Sender identity
comes from the current fenced execution, and the recipient comes from durable
direct-parent lineage. Callers cannot select arbitrary users, siblings or sessions.
Foreground one-shot children return their result directly and cannot report later.

Runtime produces a separate `subagent-settled` notice when accepted child work
becomes quiescent (completed, failed or cancelled), even if the child never
explicitly reports. Queued turns settle together; pending descendant results
reach their direct parent before that parent is considered quiescent.
The notice's outcome comes from committed Task state; its closing text remains
untrusted child-authored content. Stable IDs make settlement reconstruction
idempotent after restart. Reports and notices share one outbox in Task persistence.

Busy parents read bounded batches before the next model request. Idle child
parents receive a normal FIFO Task turn; idle conversation parents resume through
ConversationService and ActionService on the existing TaskRuntime. Multiple
notifications to the same parent coalesce. A real pending conversation turn or
confirmation takes precedence, and the same Agent's Action executions serialize.
Only model-generated replies enter chat; notification content is not persisted as
a user message and does not emit a synthetic user-memory interaction. The UI
refreshes committed parent replies through its existing Workbench subscription.

Outbox acceptance and receipt updates use atomic Task persistence. Conversation
receipts commit with the assistant reply and survive personal-space transfer;
child-parent receipts commit with the receiving child run. Uncommitted deliveries
remain available after shutdown. Checkpointed final replies can be committed on
resume without another model call. This is recoverable, at-least-once processing,
not an exactly-once guarantee for model/provider requests or external effects.

The module switch and existing capacity limits also apply to notification work.
There is no idle-parent wake during shutdown, disabled operation or a paused/
cancelled parent Task. An explicit Task pause/resume controls queued notification
work. A notification infrastructure failure pauses its Task for inspection/resume
instead of retrying indefinitely. Autonomous conversation notifications cannot
inherit approval grants or perform external-write/privileged-host actions; such
blockers must be brought back to the user. Accepted children still survive the
parent reply and browser disconnect. No provider secrets or forked parent history
are copied into child descriptors.

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
config/users/identity.sqlite3        # stable local accounts and channel bindings
config/users/<user_id>/secrets.env   # user sensitive config, copied from root .env when missing
config/users/<user_id>/config.json   # user basic/advanced config, copied from default config
```

Existing user files are never overwritten by startup or registration helpers.
Personal mail and calendar account keys are an exception to root inheritance:
they must be configured explicitly in the user's `secrets.env` or Settings and
never copy the operator's personal account. See
[Personal Assistant Accounts](playbooks/personal-assistant.md).
The identity database is independent of `memory.store_backend`; switching or
migrating Memory never changes which users can sign in. Legacy Neo4j and
`_local_users.json` accounts are imported idempotently while preserving their
user IDs and password hashes.

---

## Guest Chat

Guest chat uses the operator's main model through ConversationService. It does
not create accounts or persistent sessions, retrieve or write memory, or execute
tools, workflows, files or computer actions. Its transcript lives in the current
page and is discarded on reload or sign-in; ordinary model/HTTP logging remains
subject to the deployment's logging configuration.

`guest_chat.enabled` (`GUEST_CHAT__ENABLED`) defaults to `true` for direct loopback
connections only. Remote access requires explicit `guest_chat.allow_remote`
(`GUEST_CHAT__ALLOW_REMOTE=true`). Proxy-forwarded requests and cross-origin
browser requests are rejected by default. A publicly exposed reverse proxy must
enforce its own trusted client/origin boundary; do not use a local proxy to bypass
the remote-access switch. Guest model usage is charged to the operator.

Limits are deployment-owned: `requests_per_minute=6`, `max_concurrent=2`,
`timeout_s=60`, `max_messages=21`, `max_input_chars=16000`, and
`max_output_tokens=1024`. Each supports the corresponding `GUEST_CHAT__...` env
name. Rate/concurrency limits apply per worker; multi-worker public deployments
should also limit requests at their proxy. User settings cannot enable this path
or override these limits. Existing authenticated chat APIs still require login.

## Browser Preparation

Browser tools and Canvas verification share `computer/browser_runtime.py`.
Automatic mode first tries Playwright's matching Chromium, then installed Edge
or Chrome, and only downloads managed Chromium when none is present. Download
uses the current Python interpreter and the official Playwright CLI, inherits
its proxy/cache settings (including `PLAYWRIGHT_BROWSERS_PATH`), and never
installs OS packages or replaces an installed Edge/Chrome. Explicit channels
are strict and do not trigger a different browser installation.

| JSON field | Environment variable | Default |
| --- | --- | --- |
| `system.browser_channel` | `SYSTEM__BROWSER_CHANNEL` | empty / automatic |
| `system.browser_auto_install` | `SYSTEM__BROWSER_AUTO_INSTALL` | `true` |
| `system.browser_install_timeout_s` | `SYSTEM__BROWSER_INSTALL_TIMEOUT_S` | `120` |
| `system.browser_install_retry_delay_s` | `SYSTEM__BROWSER_INSTALL_RETRY_DELAY_S` | `60` |

These are host runtime settings, not Agent-generated policy. Concurrent callers
in one event loop share installation, failed preparation has a retry cooldown,
and timeout/cancellation terminates the installer process tree. Browser startup
options and sandbox policy are preserved for every candidate. Linux hosts may
still require administrator-installed system libraries; Promethea does not
silently escalate privileges. Canvas verification allows its existing 45-second
limit plus the configured preparation allowance. `self_evolve.browser_channel`
remains an optional explicit Canvas override; ordinary users can leave it on
Automatic. Self Evolve enablement is independent of browser availability.

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
tool and does not pass through tool routing. Promethea sends an image
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

`web.search` is a stable tool. The provider is selected at runtime from
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
| `SEARCH__FALLBACK_POLICY` | enum | `fallback` | `fallback` tries eligible providers on failure or zero results; `strict` never switches, including on zero results. |
| `SEARCH__PROVIDER_ORDER` | comma-separated ids | `brave,tavily,serpapi,searxng,duckduckgo` | User-owned provider preference; unlisted providers follow declared priority. |
| `SEARCH__BRAVE_API_KEY` | string | _(empty)_ | Enables Brave Search when provider is `auto` or `brave`. |
| `SEARCH__TAVILY_API_KEY` | string | _(empty)_ | Enables Tavily when provider is `auto` or `tavily`. |
| `SEARCH__SERPAPI_API_KEY` | string | _(empty)_ | Enables SerpAPI when provider is `auto` or `serpapi`. |
| `SEARCH__SEARXNG_URL` | URL | _(empty)_ | Enables SearXNG when provider is `auto` or `searxng`. |

Provider selection:

1. If `SEARCH__PROVIDER` names a provider, Promethea selects that registered provider.
2. If it is `auto`, available providers follow `SEARCH__PROVIDER_ORDER`, then
   their provider-declared priority.
3. With `SEARCH__FALLBACK_POLICY=fallback`, failures and zero results advance through that set
   and may reach key-free DuckDuckGo. Results record the selected provider and
   whether fallback supplied the returned result. `attempts` distinguishes empty,
   failed and successful attempts. If a provider returns a valid empty result and
   all later attempts fail or are empty, return the empty result with attempt
   diagnostics instead of fabricating results. Explicit provider mode keeps its
   existing registered-fallback set; it does not silently enable other paid engines.
4. With `SEARCH__FALLBACK_POLICY=strict`, Promethea does not silently switch
   providers after an execution failure or empty response.

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

For a local/private SearXNG endpoint, the deployment operator must additionally
allow that exact configured service base in the root environment:

```bash
SANDBOX__ALLOWED_SERVICE_URLS=["http://127.0.0.1:8888"]
```

This setting is part of global Sandbox configuration, not a user secret or model
tool argument. Restart after changing it. Scheme, host, port and base path must
match; normal `web.fetch_text`/`web.fetch_json` requests do not inherit this
exception. `SANDBOX__NETWORK_MODE=none` still denies all requests. The request
path and DNS result are checked at each redirect; provider requests cannot
redirect to a different origin. Do not disable private-network protection globally
to make one service work. SearXNG must enable JSON output in `search.formats`;
otherwise a `format=json` request can return HTTP 403. See the
[official Search API](https://docs.searxng.org/dev/search_api.html).

Provider implementation rule:

- The public tool remains `web.search`.
- Provider-specific code belongs in the web-search runtime/provider layer.
- Providers register by stable id; selection does not depend on import or
  registration order.
- Do not register separate tools such as `brave.search` or
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
as file and command tools. Browser storage and managed processes are
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

`action.max_steps` bounds the number of model decisions during one
turn. The default is `5`; per-user JSON configuration can lower or raise it without
changing routing code. Runtime validation keeps the value between `1` and `50`.
Inspection and recovery consume the same budget. A final answer-only model
request is allowed after exhaustion, without authorizing further tool actions.

| JSON Key | Environment Variable | Default |
|---|---|---|
| `max_parallel_tool_calls` | `ACTION__MAX_PARALLEL_TOOL_CALLS` | `4` |
| `observation_chars` | `ACTION__OBSERVATION_CHARS` | `16000` |
| `observation_history_chars` | `ACTION__OBSERVATION_HISTORY_CHARS` | `96000` |

Parallelism applies only to tools explicitly declared concurrency-safe. Other
calls form exclusive barriers in model order. Result budgets bound the text
payload projected into each request, not user instructions, tool schemas,
images, or identity/error metadata; they are character limits, not token counts.
They do not enable semantic conversation summarization. Retained text results
can be paged through `runtime.read_observation` under the authenticated owner.
Runtime log rotation still limits availability; older truncated records remain
explicitly truncated. All values use the existing root-env/per-user JSON rules.

`action.gaps` enables lightweight goal-relative state inside that same loop.
It adds no separate model reviewer. JSON keys and their env equivalents:

| JSON Key | Environment Variable | Default |
|---|---|---|
| `enabled` | `ACTION__GAPS__ENABLED` | `true` |
| `max_gaps` | `ACTION__GAPS__MAX_GAPS` | `12` |
| `max_updates` | `ACTION__GAPS__MAX_UPDATES` | `6` |
| `window` | `ACTION__GAPS__WINDOW` | `4` |
| `context_chars` | `ACTION__GAPS__CONTEXT_CHARS` | `2400` |

The context budget is characters, not tokens; capacity must fit all gap identities
(`context_chars >= max_gaps * 100 + 800`). Turning updates off does not delete
existing Task requirements. See [Goal Gaps](./architecture/goal-gaps.md) for
verification semantics, cost controls and limitations.

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

QQ, Telegram, Feishu, DingTalk and WeCom have real text ingress/reply plugins,
verified account pairing, an owner-scoped persistent transport inbox/outbox and
the original Gateway/Conversation/Action execution chain. Disabled by default.
QQ/Feishu/DingTalk groups require a dedicated account/member binding; Telegram
and WeCom expose private text only. Media ingestion is not supported. Enterprise
channels use application/enterprise-bot APIs, not send-only custom group webhooks.

Deployment-owned `channels/settings.py` uses root `.env` with nested `CHANNELS__...`
keys and environment > dotenv > non-secret gateway JSON > defaults precedence.
It is outside per-user/model config. Secrets are never returned by status/pairing.
`QUEUE_LIMIT` defaults to 200, `TURN_TIMEOUT_S` to 240 and `RETENTION_DAYS` to 30
(all under `CHANNELS__`). Use one process for one durable queue; restart after
credential/deployment changes. Old planning-only `TELEGRAM__...` names are not used.

See [channel operations](channels/README.md), [QQ](channels/qq.md) and
[Telegram](channels/telegram.md) for setup, pairing, limits and recovery.

---

## Section: `extensions` - tool package exposure

Promethea exposes all user-callable tools through a unified Extension Catalog:

- Tool packages in `agentkit/tools` and `extensions/community` are discovered from their manifests through the same loader; package origin does not change policy. The standard toolbox lives in `agentkit/tools/standard`.
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
    "audience_default": "business_department",
    "personal_memory_collaboration": "context_only"
  }
}
```

Fields:
- `enabled`: master switch.
- The Web UI hides enterprise operations and Runtime rejects organization capabilities when this is `false`.
- `org_id`: organization namespace id.
- `recall_priority`: `blend` or `override_persona`.
- `confirmation_queue`: keep extracted revisions pending until an organization administrator approves them.
- `audience_default`: default audience when turn metadata does not specify one.
- `personal_memory_collaboration`: `context_only` supplies personal and organization context as isolated prompt blocks; `off` suppresses personal-memory context while organization knowledge is active. Neither mode copies or dual-writes data across scopes.
- `max_upload_bytes`: max file size accepted by `/api/org-brain/ingest-file`.
- `allowed_suffixes`: accepted file suffix list for upload ingest.
- `recall_top_k_default`: default `top_k` for recall API when omitted.
- `recall_context_type_default`: default `context_type` for recall API when omitted.
- `chat_top_k`: default top-k used by chat/runtime recall.
- `chat_context_type`: default context type used by chat/runtime recall.
- `summary_label` / `summary_max_items`: summary rendering behavior.
- `extract_text_max_chars`: max chars sent into extraction prompt.
- `heuristic_max_lines` / `heuristic_max_items`: fallback extraction limits.
- `chunk_chars` / `max_chunks`: bounded document extraction window and chunk count.

API:
- `GET /api/org-brain/status`
- `POST /api/org-brain/ingest`
- `POST /api/org-brain/ingest-file` (upload file and auto-extract text before ingest)
- `POST /api/org-brain/recall`
- `POST /api/org-brain/graph`
- `GET /api/org-brain/documents`
- `DELETE /api/org-brain/documents/{document_id}`
- `POST /api/org-brain/review`
- `GET/POST /api/org-brain/members`
- `GET /api/org-brain/audit`
- `GET /api/org-brain/export`
- `POST /api/org-brain/import`
