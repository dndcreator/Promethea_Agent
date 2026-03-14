# Conversation Pipeline (Backlog 003)

## Goal

Define a stable, explicit six-stage runtime pipeline for one conversation turn, with structured stage IO objects and stage-level trace events.

## Stage Order

1. `input_normalization`
2. `mode_detection`
3. `memory_recall`
4. `planning_reasoning`
5. `tool_execution`
6. `response_synthesis`

## Stage IO Objects

- `NormalizedInput`
- `ModeDecision`
- `MemoryRecallBundle`
- `PlanResult`
- `ToolExecutionBundle`
- `ResponseDraft`

All objects are defined in `gateway/protocol.py`.

## Runtime Flow

Pipeline entry is `run_staged_pipeline` in `gateway/conversation_pipeline.py`, and `ConversationService.run_conversation` delegates to it.

For each stage:

- emit `conversation.stage.started`
- execute stage logic
- emit `conversation.stage.finished`
- on exception emit `conversation.stage.failed` and re-raise

## Current Integration Notes

- `RunContext` fields (`trace_id`, `request_id`, `session_id`, `user_id`) are propagated into stage events.
- `fast` mode can skip explicit reasoning.
- memory recall and tool execution are both represented as explicit stages even when no-op.
- pipeline output remains compatible with existing `ConversationRunOutput`.
