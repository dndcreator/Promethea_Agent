# Tool Runtime

## Goal

Standardize tool governance with unified metadata, registry, and policy enforcement.

## Core Building Blocks

- `ToolSpec` (`gateway/tools/spec.py`)
- `ToolRegistry` (`gateway/tools/registry.py`)
- `ToolPolicy` (`gateway/tools/policy.py`)

## ToolSpec

Each tool is represented with structured metadata:

- input/output schema
- capability type
- side-effect level
- permission scope
- timeout/retry/idempotency hints
- source (`local`, `mcp`, `extension`, `agent`)

## Registry

`ToolRegistry` provides a unified view across built-in tools, dynamically
discovered extensions, and external MCP tools.

- local and extension tools are registered via `register_local_tool`
- MCP services/actions are mapped via `register_mcp_services`
- `normalize_call(tool_name, params)` maps model-produced calls to a canonical registered tool id
- `resolve_for_call(tool_name, params)` returns the canonical `ToolSpec` with any manifest-declared parameterized effect applied

`agentkit/mcp/mcpregistry.py` is only the external provider configuration
directory. `MCPManager` owns protocol connections and `tools/list` discovery;
those definitions are projected into this same `ToolRegistry`. Neither the
configuration directory nor a provider can select tools or grant permissions.
Current external transport support is stdio.

A canonical id cannot be reassigned to another execution source by catalog
refresh. MCP snapshots are validated before replacement; malformed definitions
or collisions leave the previous snapshot intact. While a refresh is rejected,
MCP calls fail closed and catalog entries show `mcp_registry_refresh_failed`;
in-process tools remain usable. Correcting the provider definitions allows the
next synchronization to recover without another Registry or fallback executor.

Canonical ids use these forms:

- native factory tools: `<category>.<tool>`, for example `web.search`
- manifest-backed tools: `<service>.<action>`, for example `computer_control.execute_command`
- external MCP tools: `<provider>.<action>`

The normalizer is registry-driven. If the model swaps `service_name` and
`tool_name`, omits the full id, or marks an MCP tool as `local`, the runtime
only corrects the call when the resulting `<service>.<action>` exists in the
registered specs. This avoids hardcoded per-tool aliases while still making
tool calls tolerant of common LLM JSON mistakes.

Provider runtimes sit below `CapabilityService`; they do not create a second tool
execution path. A public tool owns its model-facing schema and presentation,
while its provider runtime owns backend registration, availability, transport,
and response mapping. Provider ids, credentials, and user identity come from
runtime context/configuration rather than model arguments.

`web.search` is the only built-in model-facing web-search id. The historical
`websearch.search`, `websearch.quick_answer`, and `websearch.news_search`
manifest surface is retired instead of maintained through router aliases.

## Policy

`ToolPolicy` enforces:

- allow/deny rules
- mode-specific restrictions
- skill allowlist hooks
- side-effect-safe defaults

Default behavior:

- `read_only` tools can run by default
- `workspace_write` stays inside the isolated workspace and is allowed unless strict policy blocks it
- `external_write` and `privileged_host_action` require one-shot confirmation
- explicit deny and host/workspace sandbox ceilings cannot be overridden by confirmation

Policy allowance is not consent. `CapabilityService.call_tool` enforces
`requires_confirmation` before hooks or dispatch for every execution source,
including calls from Reasoning, Workflow and background services without a
`RunContext`. Missing consent raises structured `TOOL_CONFIRMATION_REQUIRED` and
records a blocked tool event; the tool implementation is never entered.

Only an active Runtime `approval_scope` matching the exact submitted tool name
and arguments supplies consent. Model arguments, allowlists, invocation metadata
and approval of an outer tool or workflow do not authorize another operation.
The boundary rechecks the grant at dispatch after awaited hooks; expired grants
and changed arguments are rejected. Conversation confirmation remains the normal
user interaction, while downstream tool and sandbox checks remain defense in depth.

## Service Integration

`CapabilityService.call_tool` now uses:

1. startup or hot-reload discovery from bundled and installed manifests, plus external MCP synchronization
2. registry-driven call normalization
3. manifest-declared capability readiness
4. per-call registry resolution, including declarative action-level side effects
5. policy evaluation (runtime path with `RunContext`)
6. exact-call confirmation where required
7. workspace-bound tool invocation and platform sandbox enforcement
8. canonical result normalization and lifecycle event emission

Policy/debug context is attached into tool lifecycle events.

## Append-only capability evolution

Self Evolve extends the registry without changing Core:

1. create a versioned capability task and system-owned scaffold
2. write implementation files inside the task staging root
3. validate syntax and declared smoke tests in the process sandbox
4. publish an immutable generated extension version
5. refresh the unified ToolRegistry and invoke the new canonical tool id

Generated modules are not imported by the Gateway. `GeneratedCapabilityService`
is the trusted in-process adapter; the generated `handle(command, args)` entry
runs in a confined child process with a credential-minimized environment. The
child audit policy limits reads to the package and Python runtime, limits writes
to the call workspace, and denies network and child-process creation. External
effects must be composed through existing governed capabilities. Every generated
command is classified as `privileged_host_action`, so publishing a tool does not
grant standing execution authority.

## Capability Readiness

Tools declare host dependencies through manifest metadata such as
`requiresCapability`. `CapabilityService` asks the active capability provider for a
runtime snapshot and combines that result with MCP health and policy. Catalog
rows therefore describe whether a registered tool is callable now, not merely
whether its manifest exists.

The same readiness check runs immediately before invocation so a stale catalog
cannot authorize a capability that has since gone offline. Catalog and router
code must not branch on concrete tool names; a new capability becomes visible
by registration and manifest metadata.

Risk classification follows the same rule. Native tool classes declare
`side_effect_level` on the tool class; manifest-backed tools declare `sideEffectLevel` and,
when needed, `sideEffectSelector` in their manifest. Undeclared tools are
treated as `privileged_host_action`. The runtime never infers authority from
English words in a tool name or description.

`CapabilityService` is the only production execution authority. In-process
manifest tools invoke their registered Python adapter directly; external MCP
tools delegate transport to `MCPManager.call_service_tool`. Nested workflow runners receive a governed executor
from `CapabilityService` rather than opening another MCP path. `CapabilityService`
is also the single entry point for local tools and workspace-bound computer
capabilities. Scheduled jobs reject
calls that require interactive confirmation; approval of one foreground call
does not become standing background authority.

Model-facing calls use one shape, `{"tool_name":"<registered id>","args":{...}}`.
The registry owns whether that id is local, extension-provided, or external MCP.
Persisted older calls may still carry `agentType` and split service/action fields;
those are normalized once at the compatibility boundary and do not create a
second execution route.

Filesystem locations follow the same rule. The filesystem provider owns an
extensible semantic-location registry and advertises the locations available on
the current host. Tool schemas accept an advertised location name, while the
provider resolves it and applies the existing sandbox policy to the final path.

## Workspace Environments

The same first-class capability boundary owns tool calls, computer controllers,
the process sandbox, and workspace environments. ReAct can create application
files through filesystem/process capabilities and then register the result with
`computer_control.environment_action`.

Environment records live under the user workspace and retain task, run, and
session correlation from trusted invocation context. Static canvases and managed
process canvases share one lifecycle (`register`, `list`, `get`, `launch`,
`stop`, `remove`). Restarted process records become `interrupted` instead of
pretending that an old PID is still alive. Launch and stop remain governed by
the registry's side-effect policy and the existing OS sandbox.

The Gateway exposes only authenticated, workspace-owned preview URLs. Static
assets are path-confined; process previews proxy only the registered localhost
port. The React Canvas consumes generated public contracts through the TypeScript
SDK and embeds previews in an opaque-origin iframe sandbox.

## Temporal execution

The Runtime scheduler persists a structured trigger, a registered capability
target, and trusted user/session/workspace correlation. Trigger types are
`interval`, `at`, and `calendar`; language interpretation remains with the
model, while timestamp and recurrence calculation remain deterministic.

Due targets re-enter `CapabilityService`, so registry lookup, current user
configuration, tool policy, workspace binding, events, and sandbox enforcement
are identical to foreground execution. Tools requiring interactive approval
cannot be granted unattended authority. Claims use expiring leases to prevent
duplicate execution, and jobs declare whether missed occurrences run once or
are skipped.

## Tool Result Contract

All execution paths normalize provider output to an internal
`ToolExecutionResult` with:

- `ok`
- result value and model-facing content blocks
- structured error (`code`, `category`, `message`, `retryable`)
- optional metadata

MCP `isError`, first-party structured results, and exceptions map directly to
this contract. The Action state machine, Workbench projections, and event
consumers never infer success from display text.

Committed Observation events persist stable identities, status, structured
error data, and bounded result projections. Oversized values are represented by
a hash and preview. The live ActionRun retains the execution value needed by the
current loop without turning Runtime Event Log into a duplicate payload store.

## Runtime Action Loop

Promethea does not start the full ToT/reasoning tree for every request. Pure
chat stays on the direct path. The main model makes that choice in the same
bounded loop: it can answer immediately or select a registered capability. A
tool selection uses one Runtime-owned path:

```text
Action -> runtime Observation -> minimal verification/correction -> Answer
```

The verification step is intentionally small. The model is instructed to verify
state-changing or externally verifiable claims only when a cheap check is
available, such as file existence, readback, status, source/date, or command
result checks. If a tool fails or the observation does not prove completion, the
final answer must report failure or uncertainty instead of claiming success.

`ActionService` keeps a bounded step budget. Only a canonical `answer` becomes
the terminal assistant reply. `tool_calls`, `capability_request`, and
`capability_inspect` are Runtime control actions. Independent tool calls remain
a batch and execute concurrently.
`deep_reasoning` and `workflow` still use the heavier reasoning/tree machinery
through their own capabilities.

## Action Service Boundary

`ActionService` is the gateway first-class service for action-mode execution.
It is not a separate router, prompt assembler, or memory writer.
`ConversationService` provides the assembled model context and a versioned
CapabilitySnapshot, then the main model proposes the next canonical action.
`ActionService` is the only owner of the model/action/observation lifecycle:

- create an action run and trace
- validate state transitions before committing them
- send tool proposals through `CapabilityService` and `ToolRegistry`
- commit first-class Runtime Observations before the next model step
- pause at `waiting_confirmation` and resume the same ActionRun after approval
- preserve batch execution, cancellation, budgets, and terminal status

The model decides what to propose. Runtime owns whether a tool exists, whether
it is callable, whether confirmation is required, what executed, and what
result was observed. The deleted historical tool-call loop no longer maintains
a second set of execution facts.

`ConversationService` and `PromptAssembler` provide the canonical action
contract as part of the model-visible context. `ActionService` does not assemble
prompts and does not accept a precomputed provider response. Provider failures
therefore enter the Action state machine as Runtime failures rather than being
retried as malformed model actions.

CapabilitySnapshot is a projection, not another registry. It contains a compact
index of the complete current catalog and selected full schemas within a prompt
budget. When the model knows the evidence or effect it needs but not the correct
binding, `capability_request` asks `CapabilityService` to resolve
manifest-declared capability identifiers against current availability, policy,
side-effect limits, and learned successful-path preferences. The returned
candidates are an Observation; they do not bypass normal tool validation.
`capability_inspect` resolves omitted schemas from the same registry. Native
tools declare their input schema and required Runtime capability beside the
implementation.

Memory recall and memory writes remain owned by `MemoryService`. Deeper reasoning
remains owned by `ReasoningService`; both are exposed to the control loop through
thin registered tools. Durable workflow/checkpoint behavior remains owned by
Moirai/Workflow services. Observation-backed successful Action paths are
retained as candidate templates in the existing Moirai-backed reasoning-template
memory and may influence later candidate ordering. They do not become executable
Workflow templates automatically; completed workflows still pass the Workflow
retention gate.

Moirai also records failures and approval outcomes as process experience, then
distills versioned advisory procedures through a replaceable model backend.
See [Moirai learning](../../agentkit/tools/moirai/README.md) for ownership,
configuration, migration, and the local-model learning boundary.

## MCP Health And Tool Panel (Backlog 010)

To support a manageable MCP tool panel, runtime now includes MCP-level observability data:

- `MCPServiceHealth`: service status snapshot (`online/offline/degraded`), sync timestamps, last error, and user visibility
- `MCPToolDescriptor`: normalized MCP tool descriptor for panel/query APIs

Gateway exposes MCP query endpoints:

- `mcp.services.list`
- `mcp.service.health`
- `mcp.service.tools`
- `mcp.tools.visible`

This turns MCP from a pure invocation bridge into a diagnosable and inspectable capability source.
