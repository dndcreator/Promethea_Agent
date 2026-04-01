# Playbook: How to Add a Skill

This guide explains the current standardized way to add a skill pack in Promethea.

A skill is a structured capability object, not just a prompt file.
The runtime now uses listing-first + on-demand expansion (`skill.run`) by default.

## Runtime Model

1. The registry loads packs from `skills/packs/official/*` automatically.
2. The system prompt receives a compact skill listing (budgeted text).
3. The model calls `skill.run` only when a listed skill clearly matches the task.
4. Full instruction + runtime metadata are injected on demand.

This reduces prompt bloat and keeps the skill layer protocol-friendly.

## Step 1 - Create the Pack Directory

```text
skills/packs/official/my_skill/
|-- skill.yaml
|-- system_instruction.md
|-- tool_allowlist.yaml
|-- examples.json                  # optional
`-- evaluation_cases.json          # optional
```

## Step 2 - Define `skill.yaml`

Use JSON-compatible YAML (the current loader parses JSON syntax).

```yaml
{
  "skill_id": "my_skill",
  "name": "My Custom Skill",
  "description": "Short description for catalog display.",
  "when_to_use": "Use when user asks for X and needs Y output.",
  "category": "general",
  "version": "1.0.0",
  "enabled": true,

  "default_mode": "fast",
  "model_invocable": true,
  "execution_context": "inline",

  "allowed_tools": ["web.search", "workspace.write_file"],
  "permission_profile": "default",

  "model_override": "",
  "effort_override": "",

  "prompt_block_policy": {
    "disable": [],
    "enable": []
  }
}
```

## Step 3 - Add `system_instruction.md`

`system_instruction.md` contains the full skill instruction.
It is loaded by `skill.run` on demand (not pre-expanded in full by default).

```markdown
You are an expert assistant for X.

When task type is Y:
1) do A
2) verify B
3) output C format
```

## Step 4 - Add `tool_allowlist.yaml` (Optional)

You can keep tool controls in either `allowed_tools` (manifest) or this file.
Both are merged and deduplicated by the registry.

```yaml
["web.search", "workspace.write_file"]
```

## Step 5 - Optional Examples and Evaluation Cases

`examples.json`

```json
[
  {
    "title": "Basic flow",
    "user_input": "Do X for this input...",
    "assistant_output": "Expected high-level style/output",
    "notes": "Optional note"
  }
]
```

`evaluation_cases.json`

```json
[
  {
    "case_id": "my_skill_happy_path",
    "title": "Happy path",
    "input": "User asks for X",
    "expected_behavior": "Calls proper tools and returns structured output",
    "required_tools": ["web.search", "workspace.write_file"],
    "tags": ["happy_path"]
  }
]
```

## Step 6 - Restart and Verify

No manual registry path edits are required.
If the pack is under `skills/packs/official/*`, it is discovered automatically.

Check catalog:

```bash
curl "http://127.0.0.1:8000/api/skills/catalog" -H "X-User-Id: u1"
```

Check detail:

```bash
curl "http://127.0.0.1:8000/api/skills/my_skill" -H "X-User-Id: u1"
```

Activate for a user:

```bash
curl -X POST "http://127.0.0.1:8000/api/skills/activate" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: u1" \
  -d '{"skill_id": "my_skill"}'
```

## Step 7 - Chat Usage Path

During chat, runtime exposes a budgeted skill listing and tool `skill.run`.
The model should call `skill.run` only when needed, then execute with the returned instruction/metadata.

You can still set `requested_skill` in `/api/chat` for explicit targeting.

## Field Guide (New Standard)

- `when_to_use`: short matching hint used in listing.
- `model_invocable`: if `false`, model calls are blocked unless explicitly manual.
- `execution_context`: `inline` or `fork` (forward-compatible contract field).
- `allowed_tools`: preferred allowlist field.
- `permission_profile`: policy posture (`default`, `restricted`, `open`).
- `model_override` / `effort_override`: runtime override hints.

## Checklist

- [ ] Pack directory created under `skills/packs/official/<skill_id>`
- [ ] `skill.yaml` includes new contract fields
- [ ] `system_instruction.md` is clear and task-scoped
- [ ] Tool allowlist is defined (`allowed_tools` and/or `tool_allowlist.yaml`)
- [ ] Skill appears in `/api/skills/catalog`
- [ ] Skill detail endpoint returns instruction + metadata
- [ ] Chat path can trigger `skill.run` for this skill

## Common Mistakes

- Putting a pack outside `skills/packs/official/*` and expecting auto discovery.
- Using old-only fields like `disable_model_invocation` without mapping.
- Writing very long `when_to_use`; listing is budget-trimmed.
- Assuming full instruction is always pre-injected; current flow is lazy/on-demand.
