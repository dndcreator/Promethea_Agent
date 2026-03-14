# Prompt Assembly (Backlog 004)

## Goal

Move prompt construction from ad-hoc string concatenation to a structured block-based assembly flow.

## Core Models

- `PromptBlockType`: identity, policy, memory, tools, workspace, reasoning, response format
- `PromptBlock`: block metadata + content + priority + compaction flags

Implementation: `gateway/prompt_blocks.py`.

## Assembler

`PromptAssembler` in `gateway/prompt_assembler.py` provides:

1. `collect_blocks(run_context, mode, plan, memory_bundle, tools, user_config)`
2. `sort_blocks(blocks)`
3. `estimate_tokens(blocks)`
4. `compact_blocks(blocks, budget)`
5. `render_prompt(blocks)`
6. `assemble(...)`

## Pipeline Integration

Conversation pipeline stage `response_synthesis` now uses assembler to build the system prompt for the primary staged runtime path.

- file: `gateway/conversation_pipeline.py`
- debug output: `raw.prompt_assembly`
- run context snapshot: `run_context.prompt_blocks`

## Debug and Traceability

Assembler debug payload contains:

- used block ids
- dropped block ids
- per-block source and token estimate
- compaction flag
- estimated total tokens and budget
