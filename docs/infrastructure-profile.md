# Infrastructure Profile

Promethea is built as a **local-first Agent Runtime infrastructure**.

## Product Shape

- Runtime core: the durable system of record and execution engine.
- Built-in Assistant: the default user-facing reference application.
- CLI and HTTP API: reference access surfaces for developers and other agents.

In short:

> Local assistant is the default experience.
> Agent runtime is the core product.

## Core Abstractions

1. Conversation runtime orchestration.
2. Memory lifecycle management (recall/write/decay/cleanup).
3. Workflow execution with checkpoints and approvals.
4. Tool and skill governance with policy enforcement.
5. Security and audit with multi-user boundaries.

## Interface Boundaries

- API-first for new capabilities.
- UI should not be the only path to core runtime abilities.
- UI-only features are allowed for visualization-heavy interactions.

Current UI-bound examples:

- Memory graph drag-and-zoom interaction.
- Avatar and language preferences.
- Modal-heavy guided operations.

## Compatibility Promise (Current)

- Existing local assistant workflows remain first-class.
- Runtime abstractions are progressively exposed via API/CLI.
- No forced migration from UI-centric usage is required.

## Integrator Entry Points

- Runtime capabilities snapshot: `/api/ops/capabilities`
- Runtime abstraction contract: `/api/ops/abstractions`
- Operational guide: `/api/ops/runbook`
