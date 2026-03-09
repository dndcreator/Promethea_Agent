# Promethea Agent - Project Overview

## TL;DR

Promethea Agent is a local-first, multi-user agent platform for teams that need more than a chatbot demo.

It combines:

- gateway-first orchestration
- user-scoped sessions and config
- layered long-term memory (Hot/Warm/Cold)
- plugin and tool extensibility

## Project Status

- Stage: Active development
- Maturity: Internal-use ready, continuously evolving
- Primary language: Python
- Primary interface: Web UI + HTTP API

## Why This Project Exists

Most agent stacks optimize for quick demos. This project optimizes for operational clarity.

Key goals:

- clear module boundaries for long-term maintenance
- strict user isolation for multi-user environments
- practical extension model (plugins + tools)
- memory lifecycle beyond context-window tricks

## What Makes It Different

### 1) Multi-user by default

`user_id` is treated as a core runtime key, not an add-on.

- session ownership is scoped
- config is per-user
- memory retrieval is ownership-aware

### 2) Memory as a lifecycle, not a cache

Instead of only storing recent vectors, memory is structured into layers:

- Hot: immediate turn-level writes
- Warm: concept clustering and stabilization
- Cold: compressed summaries for long-horizon recall

A forgetting pipeline applies decay and cleanup to keep memory useful over time.

### 3) Gateway-first architecture

`gateway` orchestrates domain services; HTTP routes stay thin.

This keeps business behavior stable even when API payloads or UI workflows evolve.

### 4) Policy-aware tool execution

Tool usage is governed through policy profiles and allow/deny rules.

This is useful for balancing safety vs capability across different user roles.

## System Snapshot

```text
UI / Channels
  -> gateway/http (auth, routes, middleware)
  -> gateway services (conversation, config, memory, tools)
  -> memory + core/plugins + agentkit + extensions
  -> logs/metrics/response
```

## Core Building Blocks

- `gateway/`: runtime orchestration and service coordination
- `gateway/http/`: API boundary and auth context
- `memory/`: layered memory, recall, and forgetting
- `core/`: plugin discovery/registry/runtime
- `extensions/`: concrete plugin implementations
- `agentkit/`: MCP and tool-call orchestration
- `channels/`: inbound/outbound adapters
- `UI/`: browser frontend

## Typical Request Flow

1. User sends a chat request from UI (`/api/chat`)
2. Middleware resolves auth + user context
3. Conversation service builds model input and executes inference
4. Session messages are persisted
5. Memory pipeline asynchronously updates graph memory
6. Later turns can recall user-scoped memory into context

## Design Principles

1. Boundary discipline: `Route -> Service -> Storage`
2. User isolation is mandatory
3. Prefer one write path per domain action
4. Add features in services first, then expose API
5. Keep user errors readable, keep operator logs actionable
6. Preserve compatibility before cleanup in active systems

## Who This Is For

Best fit:

- teams building internal AI assistants
- products requiring multi-user isolation
- developers who need a maintainable architecture, not one-off scripts

Less ideal for:

- single-file prototypes
- throwaway hacks with no long-term ownership

## Operational Notes

- Config precedence: `env > user config > default config`
- Secrets should remain environment-only
- Memory features require Neo4j
- Streaming and non-stream fallback should both remain supported

## Getting Started

```powershell
pip install -r requirements.txt
python start_gateway_service.py
```

Open:

- API: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/UI/index.html`

## Near-Term Roadmap

- stronger tool governance and sandboxing controls
- better memory quality evaluation loops
- cleaner plugin authoring ergonomics
- improved observability and incident diagnostics

## Project Links

- Repository: [Promethea Agent](https://github.com/dndcreator/Promethea_Agent)
- Main README: `README.md`
