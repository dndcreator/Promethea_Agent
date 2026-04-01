# Skill Layer

## Purpose

The Skill Layer packages reusable capability units into a runtime-governed contract.
A skill in Promethea is a structured object with metadata, policy hints, and optional evaluation assets.

## Core Contracts

- `skills/schema.py`
  - `SkillSpec`
  - `SkillExample`
  - `SkillEvaluationCase`
- `skills/registry.py`
  - loads official packs from `skills/packs/official/*`
  - validates/manifests `SkillSpec`
  - resolves user-visible and user-effective skills
  - builds a budgeted skill listing prompt for runtime injection

## SkillSpec Key Fields

- Identity: `skill_id`, `name`, `description`, `version`, `category`, `enabled`
- Discovery: `when_to_use`, `model_invocable`
- Execution hints: `execution_context`, `default_mode`
- Tool and policy: `allowed_tools`, `tool_allowlist`, `permission_profile`
- Runtime overrides: `model_override`, `effort_override`
- Prompt policy: `prompt_block_policy`
- Content assets: `system_instruction`, `examples`, `evaluation_cases`

## Official Pack Layout

Each pack can include:

- `skill.yaml` (JSON-compatible YAML)
- `system_instruction.md`
- `tool_allowlist.yaml`
- `examples.json` (optional)
- `evaluation_cases.json` (optional)

## Runtime Integration

### 1) Listing-first injection

`GatewayServer._apply_skill_runtime_context(...)` builds a budgeted listing prompt from registry data and writes it into `run_context.active_skill`.
This is the default lightweight discovery surface.

### 2) Lazy expansion via tool

The runtime keeps `skill.run` available in skill allowlists.
The model calls `skill.run` to fetch full instruction + metadata only when needed.

### 3) Policy bridging

When an active skill is selected:

- skill allowlists are merged into `run_context.tool_policy.skill_allowlist`
- `permission_profile` is mapped to side-effect strictness
- `default_mode` can fill missing request mode
- `prompt_block_policy` can be applied to prompt assembly

### 4) Prompt assembly

`PromptAssembler` adds the skill listing as a `skill` prompt block, not a guaranteed full instruction dump.
This keeps context cost controlled while preserving skill discoverability.

## HTTP Surface

- `GET /api/skills/catalog`
- `GET /api/skills/{skill_id}`
- `POST /api/skills/install`
- `POST /api/skills/activate`

Catalog/detail now expose runtime-relevant skill fields (`when_to_use`, `model_invocable`, `execution_context`, allowlists, policy hints, overrides).

## Design Notes

- Registry auto-discovers official packs. Manual pack path registration is not required.
- Listing text is budgeted and can trim long descriptions.
- Legacy manifest fields are still mapped where possible for compatibility.
- Skill layer is protocol-driven: discover first, expand on demand, enforce via policy.
