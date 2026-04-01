# ADR-014: Introduce Skill Layer and Official Curated Packs

- Status: Accepted
- Date: 2026-03-13
- Backlog: 014

## Context

Promethea has runtime capabilities across memory, reasoning, tools, workspace, and workflow.
Without a skill layer, those capabilities remain fragmented across prompts and services.

## Decision

Introduce a structured Skill Layer with official curated packs.

- Define `SkillSpec` schema and related data structures.
- Load skills via `SkillRegistry` from local official pack directories.
- Integrate skill context into gateway run context.
- Use skill allowlist to constrain tool policy.
- Use skill prompt policy to govern prompt blocks.
- Include examples and evaluation cases per skill.
- Runtime listing-first injection with lazy skill expansion via `skill.run`.
- Skill discoverability and invocation gating through `when_to_use` + `model_invocable`.
- Skill runtime hints for `execution_context`, `permission_profile`, `model_override`, and `effort_override`.

## Consequences

Positive:
- Capability packaging is reusable, controllable, and testable.
- Better alignment with workflow/workspace expansion.
- Clear governance path before opening third-party marketplace.

Trade-offs:
- Additional runtime/config complexity.
- Need ongoing curation and version management for official packs.

## Rollout

Phase 1:
- ship official local packs (`coding_copilot` first)
- API catalog/install/activate endpoints
- run context integration with tool allowlist and prompt policy

Phase 2:
- add more official packs
- connect evaluation cases to regression harness
- optional UI selector improvements

## Amendment (2026-04-01)

Skill runtime has been upgraded from eager instruction injection to a listing-first flow:

1. Inject a budgeted skill listing into prompt context.
2. Keep full skill instructions behind on-demand tool call `skill.run`.
3. Merge skill policy hints into runtime tool policy without changing the core conversation contract.

This amendment keeps feature parity while reducing prompt cost and improving protocol consistency.
