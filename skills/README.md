# Skills Module

`skills` packages reusable task expertise as structured runtime objects. A skill is not a tool and not a plugin; it is instruction, metadata, examples, and optional policy hints that can be expanded on demand.

## Boundary

| Type | Purpose | Example |
| --- | --- | --- |
| Skill | Reusable task guidance and constraints. | Coding copilot behavior, review checklist, domain workflow |
| Tool | Callable operation with inputs and outputs. | `web.search`, `workspace.diff_file` |
| Extension | Drop-in package that contributes tools, channels, or services. | Community MCP-style manifest pack |

Skills may allow tools, but they do not implement tool execution themselves.

## Layout

```text
skills/
  registry.py
  schema.py
  packs/
    official/
      <skill_id>/
        skill.yaml
        system_instruction.md
        tool_allowlist.yaml
        examples.json
        evaluation_cases.json
```

## Runtime Model

1. `SkillRegistry` loads official packs from `skills/packs/official/*`.
2. Runtime injects a budgeted skill listing, not every full instruction.
3. The model calls `skill.run` only when a listed skill clearly matches.
4. Full instruction and metadata are then expanded into the current run.
5. Tool allowlists and permission hints are bridged into runtime policy.

## Key Files

- `skills/schema.py`: `SkillSpec`, examples, and evaluation case models
- `skills/registry.py`: pack discovery, validation, catalog, and listing builder
- `skills/packs/official/*`: built-in skill packs

## Change Notes

- Keep `when_to_use` short; it appears in budgeted listings.
- Keep `system_instruction.md` task-scoped; avoid broad persona or product policy.
- Put executable capability in tools, not skills.
- Add evaluation cases when the skill changes model behavior in a meaningful way.

See [docs/playbooks/how-to-add-a-skill.md](../docs/playbooks/how-to-add-a-skill.md) for the full authoring workflow.
