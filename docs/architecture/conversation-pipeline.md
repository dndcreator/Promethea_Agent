# Conversation Pipeline

## Goal

Keep one conversation turn observable without running a separate model router or
representing capabilities that were never used as completed work.

## Stage Order

1. `input_normalization`
2. `capability_discovery`
3. `model_control_loop`
4. `response_finalize`

The pipeline emits `conversation.stage.started`, `conversation.stage.finished`,
and `conversation.stage.failed` events. Its public result remains
`ConversationRunOutput`.

## Main-Model Control

`ConversationService` compiles identity, runtime context, attachments, active
skills, workspace state, and the structured CapabilityService catalog. The first main
model turn then chooses one of two paths:

- return a normal assistant reply and finish without another model request;
- invoke a registered capability and continue from its runtime observation.

HTTP, SSE, and Gateway WebSocket transports all enter through
`ConversationService`; transports do not parse model output or execute tools.
`ConversationService` assembles context, while `ActionService` alone advances
the action state machine.

The accepted bounded Observation view is retained with the action history and
checkpoint instead of being regenerated from full results on every call. The
ContextCompiler leaves existing previews unchanged while the configured bounds
fit. Under history pressure it projects from the authoritative original result,
never recursively truncating a previous preview; full content remains available
through `runtime.read_observation`. Current environment/goal/capability data is
still refreshed and is not frozen for cache reuse.

Native action and final-response requests retain identical function definitions.
The final phase remains answer/wait-only through Runtime decoding and execution
guards, not by changing the function list. This improves prefix stability but
does not guarantee provider cache hits, whose timing and storage are external.
Each model call receives a detached request list so later history updates cannot
rewrite its captured input.

For SSE, provider chunks remain inside `ActionService`. Normal assistant text
is projected to the output sink, while tool actions and protocol JSON never
become transport text. Disconnect cancellation still cancels the owning Action
task.

The projector walks only root action members, not nested tool arguments or
metadata. Draft text remains provisional until the complete canonical action
and evidence validate. Failed drafts are explicitly replaced before recovery;
SSE clients receive delta/replacement updates and the final canonical content.
An answer whose discriminator follows its content is necessarily buffered until
that discriminator arrives; streaming cannot safely infer it from nested text.

Current-turn steering enters through ConversationService and the owned pending
turn in MessageManager. ActionService admits instructions only for its active
user/session/turn, consumes them at safe boundaries, checkpoints applied command
IDs and emits durable receipt/application events. The existing Workbench
projection merges them into one localized activity per instruction. No separate
control loop, model router or Task scheduler is introduced. Guidance withdraws
an unexecuted stale proposal and clears old approvals; dispatched batches finish
and retain their Observations before replanning. It cannot undo executed effects
or increase budgets. Pending turns, final history and confirmation checkpoints
preserve guidance; restored Action checkpoints reconcile already-consumed IDs
without inserting the same user instruction again. Preparation, finalization and
confirmation waiting reject new instructions rather than falsely acknowledging
an inactive execution. The main composer keeps stop separate from steering;
the reasoning-tree control still targets that specific reasoning invocation.

Confirmation resumes the pending tool batch inside the same ActionService loop,
retaining its Action ID, model step, observations, budget, and token usage. The
transport consumes approval once, preserves the conversation turn identity, and
commits an assistant message only after successful completion. Repeated approval
requests cannot replay a consumed batch. A refusal becomes an Observation and
returns to the model for replanning or an explanation; it does not grant consent.

## Failure And Recovery

Operational failures belong to the existing action loop. Tool failures,
capability inspection/resolution failures, unavailable execution, and failed
authorization checks become failed `RuntimeObservation` records. A failed
authorization check executes none of its batch. Invalid model actions and
unsupported evidence references also become observations, without executing or
committing the rejected proposal. Each outcome returns to the main model under
the original Task authority, Action identity and step budget.

Empty or truncated model output is distinguished from transport failure in
both synchronous and streaming adapters. It returns bounded diagnostic feedback
to the next model step; no partial action executes and no token budget or
permissions are raised automatically. A transient provider failure retries the
same prepared model step within `action.max_model_recoveries`, without replaying
committed tools. The ActionService owns these retries rather than stacking them
on implicit SDK retries. A closed admission gate is not retryable and no final
model request is made through it. Unknown usage remains explicitly unknown.

Foreground chat treats the initial decision count as a checkpoint. ActionService
may grant one small extension on a newly committed successful tool result that
differs from prior results. The grant is persisted and cannot renew after a
restart. It does not override tool approval, provider admission, recovery,
cancellation, or the explicit step limits of task and background callers.

When the action budget is spent, the answer-only phase asks the model to explain
verified results and remaining obstacles, without executing further tools. If
model recovery is exhausted or admission closes, a separate Runtime status
retains committed results and marks the goal unverified; it is not an assistant
answer or evidence that the task succeeded.

Cancellation, invalid execution authority, observation/audit persistence failure,
state-machine invariant failure, and unrecoverable model transport remain Runtime
boundaries. They stop execution rather than asking a model to override them.
User-facing assistant answers always come from validated model output; separate
Runtime failure status preserves the request and available diagnostics.

SSE and WebSocket commits persist the optional reasoning tree reference on the
specific assistant message. Workspace export/import preserves that reference;
the UI does not infer a historical association from the latest session tree.

Memory recall (`memory.get_context`), deeper reasoning (`reasoning.run`), and
workflow operations are capabilities in the same catalog. Their implementation,
policy, persistence, and budgets remain owned by their Python services. The
control loop does not duplicate those decisions.

## Runtime Boundaries

For resumable work, the main model proposes `task.start` through the same
CapabilityService as other tools. The conversation Task driver captures the
original user objective and workspace; TaskRuntime schedules the Action loop
and owns its checkpoints. A different chat can discover and attach to an
owned task through `task.list` and `task.resume`, but execution still uses the
original scope. End-of-slice model and budget failures remain auditable without
replacing real obstacles in Goal Gaps.

Before every model request, including approval continuation, ConversationService
refreshes the tool projection through the same CapabilityService. PromptAssembler
replaces its dedicated capability message; it does not rebuild identity or stack
contradictory copies. Unchanged catalog and selected schemas reuse their snapshot
identity; changed state gets a new audited snapshot and tools-block hash. Exact
inspection checks registration, ownership, configuration and dependencies, while
capability resolution reports unavailable matches separately from callable ones.
The default model projection is an identifier directory, not the full Runtime
records. Definitions are resolved on demand, and only explicitly preferred,
callable tools may preload schemas. `action.capability_context_chars` bounds the
directory and snapshot reference on every refresh. Current Goal Gap data is
projected before the Conversation callback so an explicit input-budget estimate
can account for it; context assembly remains outside the Action control loop.

ContextCompiler bounds Observation text in model requests without altering the
original Runtime facts. Oversized fields include an explicit preview, source hash
and `runtime.read_observation` page request. That read-only tool uses
the existing owner-filtered Runtime Event Log, including its credential redaction
and rotation. There is no second result ledger, inference summarizer, or new
Memory write. Binary presentation blocks are not persisted as replayable text.

ActionService schedules explicitly concurrency-safe tools through a bounded pool.
Exclusive calls form barriers; Registry is consulted again before each dispatch.
Results enter the Observation sequence in model order. Cancellation stops new
dispatches, drains started tasks, preserves completed results, and distinguishes
interrupted calls with uncertain effects from calls never dispatched. An internal
scheduler failure still exits through the Runtime failure boundary.

The provider adapter never concatenates another model's output onto an already
started stream after a transport failure. Pre-output route fallback is preserved;
midstream interruption is recorded as a distinct model I/O failure.

- `PromptAssembler` and `ContextCompiler` own model input construction.
- The canonical action protocol is a non-compacted Prompt block assembled before `ActionService` starts; the state machine never appends system prompts.
- `ActionService` owns canonical action validation, state transitions, confirmation pause/resume, and Observation commits.
- `CapabilityService`, `ToolRegistry`, and `ToolPolicy` own capability truth, authorization, and execution.
- `MemoryService`, `ReasoningService`, and Workflow services retain their existing business logic.
- `SelfModelService` reads their public state projections and adds one bounded context to `RunContext`; it does not own or mutate their state.
- Its Global context combines governed cognition and identity provenance; its Situational context combines persistent working understanding, source revisions, current execution, recent event references and advisory UI context. Working understanding is personal-space scoped and is not a sliding transcript truncation or a second truth store.
- The fixed control-loop budget limits recursion; it does not interpret user language.
- `RunContext` identity fields are propagated into stage and tool events.

Passive Self Model context uses deterministic high-precision Memory search and
does not call the LLM extractor. Complex decomposition and reduction are only
available through explicit active cognition recall.

SelfModel owns revisioned attention, unresolved questions and interpretation in
`.runtime/self-model/state.json`; its observation and UI revisions do not invalidate
an otherwise current cognitive edit. `cognition.context` reads this projection;
`cognition.update_situation` uses the cognitive revision. No background extractor
or extra model loop is introduced. Ambient schedules the existing execution chain
and consumes semantic interaction events; it does not maintain another mind.

## Reference Boundaries

These mechanisms adapt existing services rather than import another harness:

- [DeepSeek Harness Agent Loop](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/core/agent-loop/README.md): per-step assembly, request-error recovery boundaries, opt-in bounded parallelism, exclusive barriers and cancellation/result convergence. Its plugin faults can still end a turn; not every Runtime fault becomes a model reply.
- [Claude Code execution model](https://code.claude.com/docs/en/how-claude-code-works): observe/action/verification, deferred tool definitions and context-pressure management. Promethea's result projection is deterministic bounding, not Claude Code's semantic auto-compaction.
- [Codex harness platform](https://developers.openai.com/blog/codex-as-a-platform): the host application retains business rules, tools and execution boundaries while the harness owns the loop. This comparison uses official documentation, not claims about private model behavior.
