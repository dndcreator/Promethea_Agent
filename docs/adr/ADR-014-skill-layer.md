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
