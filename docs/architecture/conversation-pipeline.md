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

- return an `answer` action and finish without another model request;
- invoke a registered capability and continue from its runtime observation.

Memory recall (`memory.get_context`), deeper reasoning (`reasoning.run`), and
workflow operations are capabilities in the same catalog. Their implementation,
policy, persistence, and budgets remain owned by their Python services. The
control loop does not duplicate those decisions.

## Runtime Boundaries

- `PromptAssembler` and `ContextCompiler` own model input construction.
- `CapabilityService` and `ToolPolicy` own capability discovery, authorization, and execution.
- `MemoryService`, `ReasoningService`, and Workflow services retain their existing business logic.
- `SelfModelService` reads their public state projections and adds one bounded context to `RunContext`; it does not own or mutate their state.
- The fixed control-loop budget limits recursion; it does not interpret user language.
- `RunContext` identity fields are propagated into stage and tool events.
