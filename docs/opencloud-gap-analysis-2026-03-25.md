# OpenClaw Alignment Notes (2026-03-25)

Date: 2026-03-25

This note captures how Promethea docs were aligned with OpenClaw-style documentation principles without losing Promethea-specific architecture.

## Sources Used

- OpenClaw repo docs index and prose style:
  - https://github.com/openclaw/openclaw
  - https://raw.githubusercontent.com/openclaw/openclaw/main/docs/index.md
  - https://raw.githubusercontent.com/openclaw/openclaw/main/docs/prose.md
- OpenClaw docs site structure examples:
  - https://docs.openclaw.ai/skills
  - https://docs.openclaw.ai/plugins/manifest

## Alignment Principles

1. Strong entry path first, deep docs second.
2. Task-driven docs over module-only docs.
3. Clear "read this if" guidance per page.
4. Copy-paste examples for CLI/API integration.
5. Explicit boundaries and failure modes, not only happy path.

## Changes Applied in Promethea

### 1) Docs Hub Restructure

`docs/README.md` now gives reader paths:
- run in 5 minutes
- understand architecture
- integrate via API/CLI

### 2) CLI and API Docs Shifted to Integration Contracts

- `docs/cli-reference.md` now includes:
  - real command groups matching current CLI
  - user journeys
  - troubleshooting and smoke recommendations
- `docs/api-reference.md` now includes:
  - integration path
  - discovery-first workflow
  - minimal curl examples
  - normalized error contract reminders

### 3) Runtime Overview Rewritten for Readability

- `docs/runtime-overview.md` was rewritten from a corrupted/garbled state to a clean architecture narrative.
- Core loop is explicitly documented:
  - complexity gate -> ReAct/ToT -> workflow-mediated tool execution -> observation feedback

### 4) Official Tooling Visibility Added

- New page: `docs/official-tools.md`
- Documents built-in official tool categories and runtime visibility rules.

## What We Deliberately Did Not Copy

- OpenClaw-specific branding, naming, and UX language.
- Feature claims that are not present in Promethea runtime.

Promethea keeps its own differentiation:
- local assistant shell + protocol-first runtime
- memory-governed and workflow-aware runtime behavior
- user-scoped boundaries and auditable execution
