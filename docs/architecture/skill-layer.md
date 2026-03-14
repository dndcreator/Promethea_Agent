# Skill Layer (Backlog 014)

## Purpose

Skill Layer packages reusable task capabilities into structured, governed units.
A skill is not just prompt text. It combines:
- system instruction
- tool allowlist
- prompt block policy
- examples
- evaluation cases

This turns scattered runtime abilities into stable, evaluable capability packs.

## Core Design

- `skills/schema.py`
  - `SkillSpec`
  - `SkillExample`
  - `SkillEvaluationCase`
- `skills/registry.py`
  - loads official curated packs from `skills/packs/official/*`
  - validates and materializes `SkillSpec`
  - resolves effective skill by `requested_skill` and user config

## Official Pack Layout

Each official pack follows:
- `skill.yaml`
- `system_instruction.md`
- `tool_allowlist.yaml`
- `examples.json`
- `evaluation_cases.json`

Current first pack:
- `coding_copilot`

## Runtime Integration

`GatewayServer` now:
- builds `RunContext` per chat turn
- resolves and binds active skill into run context
- injects `skill_allowlist` into `run_context.tool_policy`
- applies skill default mode when request mode is absent

`ConversationService.prepare_chat_turn` now:
- merges skill system instruction into base system prompt

`PromptAssembler` now:
- supports `skill` prompt block
- supports `prompt_block_policy` filtering (`enable`/`disable`)

## HTTP Integration

`/api/skills` now serves official skill catalog/details and activation:
- `GET /api/skills/catalog`
- `GET /api/skills/{skill_id}`
- `POST /api/skills/install`
- `POST /api/skills/activate`

`/api/chat` now accepts:
- `requested_skill`
- `requested_mode`

## Notes

To avoid new dependencies, `.yaml` pack files currently accept JSON syntax (JSON is valid YAML subset for our use case).
