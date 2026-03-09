# Promethea Agent

Promethea Agent is a local-first, multi-user agent runtime built around one rule: keep boundaries clear.

It provides a web UI, HTTP API, session management, user-scoped memory, and plugin-based extensions in one repository.

## Contents

- [Why This Exists](#why-this-exists)
- [Differentiation](#differentiation)
- [Who This Is For](#who-this-is-for)
- [Quick Start](#quick-start)
- [How The System Is Organized](#how-the-system-is-organized)
- [Design Rules (Project-Wide)](#design-rules-project-wide)
- [Request Lifecycle](#request-lifecycle)
- [Configuration Model](#configuration-model)
- [Module Map](#module-map)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Open Source Baseline](#open-source-baseline)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

## Why This Exists

Most agent projects are easy to demo and hard to maintain.

This project is designed for long-lived operation:

- local-first deployment for fast iteration
- strict user isolation for multi-user safety
- explicit module boundaries for low-risk maintenance
- extension model that does not require rewriting core runtime

## Differentiation

This section describes what is intentionally different about this project.

### 1) Multi-user is a first-class runtime constraint

Many agent repos are single-user at heart and add accounts later.

Promethea starts from user scoping:

- API auth resolves a concrete `user_id`
- session operations are user-scoped
- config is persisted under `config/users/<user_id>/config.json`
- memory ownership is enforced in session scope helpers (`memory/session_scope.py`)

Design impact:

- fewer cross-user leakage risks
- easier productionization for teams/internal tools
- some extra code in route/service layers, by design

### 2) Memory is layered and operational, not a demo vector store

Memory is built as a lifecycle:

- hot layer: immediate writes from current turns
- warm layer: clustering/concept stabilization
- cold layer: long-term summaries
- forgetting pass: decay + cleanup

This design targets long-horizon chats where context windows are not enough.

Tradeoff:

- more moving parts than a simple embedding cache
- better control over retention and recall quality over time

### 3) Gateway-first orchestration, not route-first sprawl

`gateway` is the orchestrator. `gateway/http` is only the boundary.

Why this matters:

- business behavior stays in service modules
- HTTP payload changes do not force deep rewrites
- adding channels does not duplicate core logic

### 4) Tool use is policy-driven, not binary on/off

Tool access is controlled by policy profiles (`minimal`, `coding`, `full`) and allow/deny sets.

This is practical for real deployment:

- safer defaults for general users
- broader permissions for coding/ops users
- per-provider overrides when needed

### 5) Reasoning outcomes are gated before persistence

Reasoning output is not blindly recorded.

The runtime supports outcome assessment and optional human confirmation before storing successful patterns.

Goal:

- reduce accumulation of low-quality reasoning artifacts
- keep long-term memory cleaner in real usage

## Who This Is For

### Good fit

- teams building an internal assistant with multiple user accounts
- projects that need both UI and API from one runtime
- developers who care about maintainability more than quick hacks
- systems that need memory behavior beyond context-window stuffing

### Not a good fit

- single-file prototype needs
- "just one script" automation tasks
- use cases where no user isolation is required

## Quick Start

### 1. Requirements

- Python 3.10+
- Neo4j (optional, only needed for memory features)

### 2. Install

```powershell
pip install -r requirements.txt
```

Optional editable install:

```powershell
pip install -e .
```

### 3. Configure

Create `.env` in repo root (or copy from `env.example`):

```env
API__API_KEY=your_api_key_here
AUTH__SECRET_KEY=replace_with_a_long_random_value
```

Enable memory only if needed:

```env
MEMORY__ENABLED=true
MEMORY__NEO4J__ENABLED=true
MEMORY__NEO4J__URI=bolt://127.0.0.1:7687
MEMORY__NEO4J__USERNAME=neo4j
MEMORY__NEO4J__PASSWORD=your_password
MEMORY__NEO4J__DATABASE=neo4j
```

Enable voice with compact settings (optional):

```env
# reuse API__API_KEY by default
VOICE__PROVIDER=openai
VOICE__MODEL=gpt-4o-mini-tts
VOICE__VOICE=alloy
```

### 4. Run

```powershell
python start_gateway_service.py
```

Open:

- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/UI/index.html`

## How The System Is Organized

```text
client (UI/channels)
  -> gateway/http (routing, auth, middleware)
  -> gateway services (conversation, config, memory, tools)
  -> memory/core/agentkit/extensions
  -> response/logs/metrics
```

The gateway is orchestration. Business logic should live in services. Persistence details should stay in storage modules.

## Design Rules (Project-Wide)

These rules apply to every module in this repository.

### 1) Respect the boundary chain

`Route -> Service -> Storage`

- Routes parse input, run auth checks, and shape output.
- Services implement business behavior.
- Storage layers persist and retrieve data.

Do not skip layers unless there is a proven performance reason.

### 2) User isolation is non-negotiable

Any session/config/memory operation must be scoped by `user_id`.

If a shortcut bypasses `user_id`, it is a bug.

### 3) Prefer one write path per domain action

For config updates, prefer `POST /api/config/update`.

Parallel write paths are a common source of silent data drift.

### 4) Add features in service layer first

Expose new routes only after the service behavior is stable and testable.

### 5) Fail loudly for operators, clearly for users

- user-facing messages should be readable
- logs should include enough context to debug quickly

### 6) Compatibility beats cleanup in active systems

When API shapes change, keep compatibility where practical and remove old paths in a controlled follow-up.

## Request Lifecycle

Typical chat request flow:

1. UI calls `POST /api/chat`
2. middleware resolves user context
3. conversation service builds prompt + calls model
4. message manager commits turn data
5. memory pipeline updates graph data asynchronously
6. future turns can recall user-scoped memory

## Configuration Model

Precedence (low to high):

1. `config/default.json`
2. `config/users/<user_id>/config.json`
3. environment variables (`.env`)

Notes:

- keep secrets in environment variables
- keep user overrides minimal and explicit
- keep defaults stable for first-run experience

## Module Map

```text
gateway/         runtime orchestration and core services
gateway/http/    API boundary (auth, routes, middleware)
memory/          layered memory + recall/forgetting
core/            plugin framework (discovery/registry/runtime)
channels/        inbound/outbound channel adapters
computer/        host-side control primitives
agentkit/        MCP + tool-call orchestration + policy
extensions/      concrete plugin implementations
config/          default and per-user config data
UI/              browser client
tests/           regression and integration coverage
```

## Development Workflow

### Install dev dependencies

```powershell
pip install -e .[dev]
```

### Before opening a PR

1. confirm boundary placement (route/service/storage)
2. confirm `user_id` scoping on touched paths
3. confirm no duplicate write paths were introduced
4. run relevant tests

### If you touched memory logic

Always run memory regression tests before merge.

### If you touched streaming UI

Validate SSE path and JSON fallback path.

## Testing

Run all tests:

```powershell
pytest -q tests/
```

Or use the unified runner:

```powershell
python tests/run_all_tests.py
python tests/run_all_tests.py --coverage
```

Recommended fast regression set:

```powershell
pytest -q tests/test_message_manager_turns.py tests/test_memory_regressions.py tests/test_conversation_queue.py
```

## Open Source Baseline

This repository includes standard open-source collaboration files:

- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `SUPPORT.md`
- `CHANGELOG.md`
- `.github/workflows/ci.yml`
- `.github/ISSUE_TEMPLATE/*`
- `.github/pull_request_template.md`

## Troubleshooting

### `API key is not configured`

Set `API__API_KEY` in `.env` and restart service.

### `Memory system not enabled`

Set both:

- `MEMORY__ENABLED=true`
- `MEMORY__NEO4J__ENABLED=true`

### Neo4j connection issues

Check in order:

1. Neo4j is running
2. URI is correct (`bolt://127.0.0.1:7687` by default)
3. username/password/database are correct

### UI opens but chat fails

Check gateway logs first, then verify `/api/config` returns expected model settings for the current user.

## Documentation

- `QUICK_START.md`
- `gateway/README.md`
- `gateway/http/README.md`
- `memory/README.md`
- `core/README.md`
- `channels/README.md`
- `computer/README.md`
- `agentkit/README.md`
- `extensions/README.md`
- `config/README.md`
- `UI/README.md`
- `tests/README.md`


