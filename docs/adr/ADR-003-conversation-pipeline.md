# ADR-003: Introduce Staged Conversation Pipeline

## Status

Accepted

## Date

2026-03-11

## Context

Conversation orchestration previously mixed prompt assembly, memory recall, reasoning, tool execution, and response generation inside one large service flow. This made boundary ownership unclear and increased extension risk.

## Decision

Adopt a fixed six-stage pipeline for single-turn runtime execution:

1. Input Normalization
2. Mode Detection
3. Memory Recall
4. Planning / Reasoning
5. Tool Execution
6. Response Synthesis

Each stage must expose explicit input/output models and emit stage lifecycle events (`started`, `finished`, `failed`).

## Consequences

### Positive

- Clear extension points for prompt, memory, reasoning, and tools.
- Better traceability and failure localization.
- Reduced god-method pressure in `ConversationService`.

### Trade-offs

- Slightly more orchestration code.
- Temporary adapter logic while legacy internals are migrated stage-by-stage.

## Implementation Mapping

- Stage models: `gateway/protocol.py`
- Pipeline runner: `gateway/conversation_pipeline.py`
- Service entry: `gateway/conversation_service.py::run_conversation`
- Tests: `tests/test_conversation_pipeline_staging.py`
