# ADR-004: Introduce Prompt Block Assembler

## Status

Accepted

## Date

2026-03-11

## Context

Prompt logic was spread across conversation, memory, reasoning, and tool paths, creating fragile coupling and weak observability.

## Decision

Introduce a block-based prompt assembly mechanism with explicit block model and assembler lifecycle.

- Prompt blocks are typed, prioritized, token-estimated, and optionally compactable.
- Assembler is integrated into staged conversation runtime for system prompt generation.
- Assembly debug metadata is exposed for runtime inspection.

## Consequences

### Positive

- Prompt sources become explicit and inspectable.
- Token budgeting/compaction has a dedicated control point.
- Future prompt features can be integrated as new blocks, not ad-hoc string patches.

### Trade-offs

- Slight increase in orchestration complexity.
- Existing non-staged or legacy paths still need gradual migration.

## Implementation Mapping

- Models: `gateway/prompt_blocks.py`
- Assembler: `gateway/prompt_assembler.py`
- Pipeline hookup: `gateway/conversation_pipeline.py`
- Tests: `tests/test_prompt_assembler.py`, `tests/test_conversation_pipeline_staging.py`
