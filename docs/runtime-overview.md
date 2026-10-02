# Promethea Runtime Overview

## Work Domains

Conversation and Task are separate first-class domains. Conversations own user
interaction; tasks own durable goals and execution runs. See
`docs/architecture/task-runtime.md`.

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

The supported language and transport boundaries are documented in
`docs/architecture/protocol-boundaries.md`. Python Core services remain
in-process; `/openapi.json`, the Gateway WebSocket protocol, and MCP are the
external integration surfaces.

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
- a bounded, user-scoped Self Model projection for the current run

### Gateway Request/Response

Every channel should map input into a unified gateway request model and receive a unified response model.

## Pipeline (Single Turn)

### Stage 1: Input Normalization

The runtime normalizes transport-level payload into internal request semantics.

Outputs:
- normalized user message
- user/session identity
- initial `RunContext`

### Stage 2: Capability Discovery and Cognitive Budget

The runtime reads the current CapabilityService catalog and assembles required identity,
context, and policy blocks. It does not call a separate router model. The first
main-model turn decides whether to answer directly or select a registered
capability such as memory recall, a normal tool, deeper reasoning, or workflow.

The choice is semantic, but execution is constrained by code:

- identity and safety blocks cannot be disabled by the model;
- only catalog entries marked callable can execute;
- ToolPolicy and permissions are checked again at invocation;
- the control-loop step budget is fixed by the runtime;
- MemoryService, ReasoningService, and Workflow services retain their own policies and persistence.

A direct answer therefore takes one model request. A capability call adds model
turns only after a real runtime observation. Simple tool work stays in the
lightweight loop; only `reasoning.run` starts the full reasoning tree.

### Stage 3: ReAct + ToT Planning/Reasoning

For complex tasks, Promethea enters ReAct loop and uses ToT-style branching inside reasoning steps.

Loop intent:
- think
- decide next action (memory/tool/continue/done)
- consume observations
- replan if needed

Procedural replay behavior:
- on similar tasks, runtime can try procedural action replay first
- replay is intent/capability driven (semantic), not strictly tool-name bound
- if replay fails, runtime falls back to explicit re-planning

### Stage 4: Tool Execution via Workflow Bridge

When reasoning decides to act, tool action is executed through workflow-compatible path (Moirai/workflow engine bridge when enabled).

Execution guarantees:
- policy checks
- traceability
- recoverable run metadata
- runtime can compile one step from ExecutionMindGraph to currently available tools

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
- stable blocks first (identity/soul)
- dynamic blocks second (memory/reasoning/tools/policy/workspace)
- optional budget compaction with block-level debug output

`PromptAssembler` runs in two places:
- Canonical staged pipeline: the model-control-loop assembly calls it when the run does not already provide prebuilt messages.
- Streaming/legacy chat path: `ConversationService.prepare_chat_turn` calls it before handing messages to the LLM.

The assembler receives structured runtime inputs instead of ad-hoc string patches:
- `PlanResult`: the stable base identity for the initial model turn.
- `MemoryRecallBundle`: empty on the initial turn; recalled context arrives as a runtime observation.
- `ToolExecutionBundle`: the live structured capability catalog and code-enforced step budget.
- `RunContext`: skill listing, tool policy, workspace handle, org context, Self Model context, input payload, token budget, and prompt block policy.
- `user_config`: merged non-secret behavior defaults plus user overrides.

Current prompt blocks:
- `identity`: Promethea's base runtime identity and language policy.
- `soul_core`: the read-mostly soul prompt, style/personality only.
- `memory`: recalled personal memory context.
- `self_model`: bounded current/evolving/uncertain cognition projected by `SelfModelService`; it is not a second memory store.
- `org_context`: enterprise/org brain context when `org_brain.enabled=true`.
- `reasoning`: final reasoning decision summary when explicit reasoning is used.
- `skill`: active skill/tool registration guidance.
- `tools`: tool availability guidance.
- `workspace`: current workspace handle.
- `policy`: runtime tool/security policy.
- `response_format`: user-level response style.

If callers intentionally pass fully prebuilt messages to the staged pipeline, the pipeline preserves those messages and marks prompt assembly as `source=prebuilt_messages`. Normal chat entrypoints should avoid bypassing `prepare_chat_turn` unless they are deliberately replaying or continuing a previously assembled conversation.

### Stage 7: Memory Write Governance

Before long-term persistence, memory write gate evaluates candidate writes (`allow/deny/defer`).

### Stage 8: Audit and Trace Flush

Runtime emits structured events for later inspection and debugging.

### Runtime Soul Evolution (Async Side Loop)

After response synthesis, runtime may trigger asynchronous soul evolution:
- input: latest user message + assistant response + current `persona.soul`
- decision: LLM returns `should_update` and candidate soul text
- guardrails: style-only scope, durable preference requirement, rate limit, max length
- persistence: user-scoped config update to `persona.soul.*`

This side loop does not block current turn latency.

## Capability Layers

### Memory

- hot/warm/cold style recall and storage behavior
- recall policy by mode
- write gating before persistence
- procedural memory assets (reasoning templates, action templates, mind graphs) are persisted under `brain/basal_ganglia`

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
- explicit runs are hosted by TaskRuntime independently of client connections

### Task and Workbench

- TaskService owns the durable goal state machine and user control commands
- TaskRuntime continues explicit workflow runs after the initiating request returns
- Task revision and execution-epoch fences reject stale commands and stale workers
- Task Runs retain process Attempts; open attempts become explicit `interrupted` history after restart
- Workflow Step Attempts persist before execution and carry stable tool idempotency keys
- durable retry/backoff plus a recovery supervisor resumes due provider/tool work without a client connection
- running TaskRuntime runs are recovered from persisted Workflow checkpoints after restart
- WorkbenchProjection materializes Task, Run, Tool, Memory, Workflow, and Artifact activity into one read model

### Workspace

- file operations under scoped workspace boundary
- path safety and user ownership checks

### Reasoning

- explicit state transitions
- iterative plan-act-observe
- configurable budget controls
- full reasoning tree only starts when the cognitive budget explicitly allows it

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
