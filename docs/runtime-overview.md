# Promethea Runtime Overview

This document explains how Promethea executes one request end to end.

## Why This Exists

Promethea is not just prompt-in, text-out.
It is a runtime that coordinates identity, memory, reasoning, tools, workflow, and safety boundaries in one execution loop.

If you only read one architecture file, read this one.

## Runtime Identity

Promethea runtime has one core contract:
- same core capability should be reachable from UI, CLI, and API
- transport changes, runtime semantics do not

UI is a shell, not the engine.

## Core Objects

### SessionState

Long-lived state across turns:
- `session_id`
- `user_id`
- channel and workspace context
- conversation continuity metadata

### RunContext

Single-run execution context:
- normalized input
- identity and trace metadata
- effective policy and config
- available tools and memory scope

### Gateway Request/Response

Every channel should map input into a unified gateway request model and receive a unified response model.

## Pipeline (Single Turn)

### Stage 1: Input Normalization

The runtime normalizes transport-level payload into internal request semantics.

Outputs:
- normalized user message
- user/session identity
- initial `RunContext`

### Stage 2: Complexity Gate

Runtime evaluates whether the request is simple or complex.

Decision objective:
- simple: direct response path
- complex: explicit reasoning path

### Stage 3: ReAct + ToT Planning/Reasoning

For complex tasks, Promethea enters ReAct loop and uses ToT-style branching inside reasoning steps.

Loop intent:
- think
- decide next action (memory/tool/continue/done)
- consume observations
- replan if needed

### Stage 4: Tool Execution via Workflow Bridge

When reasoning decides to act, tool action is executed through workflow-compatible path (Moirai/workflow engine bridge when enabled).

Execution guarantees:
- policy checks
- traceability
- recoverable run metadata

### Stage 5: Observation Feedback

Tool outputs and verification results are converted to observations and fed back into reasoning loop.

This creates the required closed loop:
- decision -> action -> observation -> next decision

### Stage 6: Response Synthesis

Runtime composes final user-visible response from:
- current user input
- recalled memory
- reasoning summary
- tool/workflow observations

Prompt assembly model:
- stable blocks first (identity/persona/soul)
- dynamic blocks second (memory/reasoning/tools/policy/workspace)
- optional budget compaction with block-level debug output

### Stage 7: Memory Write Governance

Before long-term persistence, memory write gate evaluates candidate writes (`allow/deny/defer`).

### Stage 8: Audit and Trace Flush

Runtime emits structured events for later inspection and debugging.

### Runtime Persona/Soul Evolution (Async Side Loop)

After response synthesis, runtime may trigger asynchronous soul evolution:
- input: latest user message + assistant response + current `persona.soul`
- decision: LLM returns `should_update` and candidate soul text
- guardrails: style-only scope, rate limit, max length
- persistence: user-scoped config update to `persona.soul.*`

This side loop does not block current turn latency.

## Capability Layers

### Memory

- hot/warm/cold style recall and storage behavior
- recall policy by mode
- write gating before persistence

### Enterprise Context (Org Brain)

- optional `org_brain` capability, disabled by default
- org-scoped ingest and recall (`org_id`) via dedicated API routes
- prompt injection only when `org_brain.enabled=true` and recall returns context
- no coupling to personal mode when disabled

### Tools and MCP

- unified local tools + MCP tools + agent tools
- ToolPolicy enforcement at runtime
- auditable invocation path

### Workflow

- resumable execution
- checkpoint-aware progression
- approval/pause/resume support

### Workspace

- file operations under scoped workspace boundary
- path safety and user ownership checks

### Reasoning

- explicit state transitions
- iterative plan-act-observe
- configurable budget controls

## Contracts Over Assumptions

Use discovery surfaces rather than static assumptions:
- `GET /api/ops/surfaces`
- `GET /api/ops/protocol`
- `GET /api/ops/methods`
- `GET /api/ops/http-contracts`
- `GET /api/ops/readiness`

## Typical Failure Modes

- dependency unavailable (MCP/provider/Neo4j)
- policy denies side-effect tools
- tool returns weak/failed observation
- workflow paused waiting approval

These are runtime states, not necessarily runtime bugs.

## Practical Debug Order

1. Check readiness and service status.
2. Check tool visibility and policy.
3. Check reasoning trace and observation quality.
4. Check memory recall/write decisions.
5. Check workflow state (paused/waiting/failed).

## Summary

Promethea runtime is a protocolized execution system with a local assistant shell.

The key differentiator is the closed loop:
- complexity gate
- explicit reasoning
- workflow-mediated action
- observation feedback
- governed persistence
