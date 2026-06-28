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

### Stage 2: Cognitive Budget Gate

Runtime evaluates how much cognition the request deserves before it assembles the full prompt.

Decision objective:
- `direct`: answer from the core prompt and normal context; no tool loop and no reasoning tree.
- `light_action`: allow a small number of tool calls for simple current-data lookup, calculation, search, or one-shot file/workspace action; no full reasoning tree.
- `deep_reasoning`: use the full reasoning tree for multi-step investigation, planning, debugging, comparison, design, or research synthesis.
- `workflow`: use explicit long-running workflow orchestration.

Before prompt assembly, Promethea also runs a lightweight prompt policy routing
pass. This first pass exposes only a minimal router system block and asks for
structured JSON, not a user-facing answer. The router returns an execution budget:

- `cognitive_mode`: `direct | light_action | deep_reasoning | workflow`
- `reasoning_budget`: `none | small | large`
- `tool_budget`: bounded number of tool-loop turns
- `memory_budget`: `none | brief | full`
- `need_user_visible_reasoning`: whether the UI should expect a visible reasoning tree

The router may also suggest dynamic blocks:
- memory recall
- reasoning/deep mode when `reasoning_budget=large`
- tools/workspace context
- organization context

The router cannot disable identity, soul core, or safety/policy blocks.
Those remain code-enforced runtime contracts.

Only `reasoning_budget=large` starts the full reasoning tree. Simple tool tasks
should stay in `light_action`, so a request such as checking a current stock
price can call a tool briefly without paying the latency of full ReAct/ToT
planning. If the light action fails, the runtime reports the failure or asks
whether to continue with a deeper attempt instead of silently escalating forever.

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
- Canonical staged pipeline: `stage_response_synthesis` calls it when the run does not already provide prebuilt messages.
- Streaming/legacy chat path: `ConversationService.prepare_chat_turn` calls it before handing messages to the LLM.

The assembler receives structured runtime inputs instead of ad-hoc string patches:
- `prompt_policy`: LLM/heuristic routing result for dynamic block suggestions.
- `PlanResult`: base identity prompt, or the reasoning service's rewritten system prompt.
- `MemoryRecallBundle`: recalled personal memory context, when recall is allowed and available.
- `ToolExecutionBundle`: whether tool capability is active for this run.
- `RunContext`: skill listing, tool policy, workspace handle, org context, input payload, token budget, and prompt block policy.
- `user_config`: merged non-secret behavior defaults plus user overrides.

Current prompt blocks:
- `identity`: Promethea's base runtime identity and language policy.
- `soul_core`: the read-mostly soul prompt, style/personality only.
- `memory`: recalled personal memory context.
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
