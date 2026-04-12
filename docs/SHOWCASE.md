# Promethea Showcase

## What this project is

Promethea is a local-first agent runtime for long-lived AI systems. It provides a runtime core where memory, workflow, policy, audit, and multi-user boundaries are part of the default execution model.

## What makes it interesting

- Memory is treated as a runtime lifecycle, not only context stuffing.
- Workflow is resumable and auditable, instead of one-shot chains.
- Tool execution is policy/sandbox aware, with traceability.
- Multi-user safety is modeled explicitly across sessions, memory, config, and workspace scopes.
- It can be explored locally through UI, API, CLI, and channel adapters.

## Core capabilities

- Gateway-first runtime orchestration (`gateway/`)
- Pluggable memory backends (`memory/`)
- Resumable workflow engine and artifact writes
- Structured trace/audit signals for operations and security
- Tool/policy/runtime integration via `agentkit` and gateway services
- Multi-surface access: Web UI, HTTP API, CLI

## Example runtime scenarios

- A long-lived assistant that remembers user preferences across sessions.
- A team runtime where multiple users share infrastructure but keep strict data boundaries.
- A policy-constrained automation path that logs sensitive actions for review.
- A paused workflow that resumes with human approval and continues artifact delivery.

## What can already be tried today

- Start runtime locally and open the built-in UI.
- Use CLI to run status/doctor/reasoning/workflow/security commands.
- Inspect memory graph and recall runs.
- Trigger workflow runs and inspect checkpoints.
- Verify audit/security report endpoints.

Suggested entry points:

- [README.md](../README.md)
- [QUICK_START.md](../QUICK_START.md)
- [docs/reference/cli.md](./reference/cli.md)
- [docs/reference/http-api.md](./reference/http-api.md)

## What is still in progress

- Broader public benchmark coverage and reporting depth
- Packaging and release-process polish
- More polished external demo assets (video/screenshots/hero diagrams)
- Ongoing docs consistency and onboarding refinements

This is a **public preview** stage: already explorable and useful, still actively evolving.
