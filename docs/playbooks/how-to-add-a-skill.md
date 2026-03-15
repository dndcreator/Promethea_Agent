# Playbook: How to Add a Skill

A **Skill** in Promethea is a reusable capability pack that bundles:

- A system instruction injected into the conversation
- A tool allowlist restricting which tools are available in this mode
- A default reasoning mode
- Example interactions for evaluation

Skills let you switch the agent's persona, capability set, and operating policy without touching the core runtime.

---

## Step 1 — Create the skill directory

```
skills/packs/official/my_skill/
├── skill.yaml            ← metadata and policy
├── system_instruction.md ← injected system prompt
├── tool_allowlist.yaml   ← which tools are allowed
└── examples.json         ← evaluation cases (optional)
```

---

## Step 2 — Write `skill.yaml`

```yaml
# skills/packs/official/my_skill/skill.yaml

skill_id: my_skill
display_name: "My Custom Skill"
description: "A skill for doing X."
version: "1.0.0"
author: "your-name"

# Reasoning mode applied when this skill is active
default_mode: fast         # fast | deep | workflow

# Whether workspace operations are permitted
workspace_enabled: true

# Whether to inject this skill's system_instruction.md
inject_system_instruction: true

# Tags for discovery
tags:
  - productivity
  - writing
```

---

## Step 3 — Write `system_instruction.md`

```markdown
You are an expert at X.

When the user asks about Y, always do Z first.

Output format: ...
```

This file is loaded and injected as a prompt block during `RunContext` construction.

---

## Step 4 — Write `tool_allowlist.yaml`

```yaml
# Restrict which tools this skill can use.
# Use "*" to allow all tools.
# Use an empty list [] to block all tools.

allowed_tools:
  - weather.current
  - web.search
  - workspace.write_document
```

---

## Step 5 — Register the skill

Open `skills/registry.py` and add the pack path:

```python
OFFICIAL_PACKS = [
    "skills/packs/official/coding_copilot",
    "skills/packs/official/my_skill",   # ← add this
]
```

---

## Step 6 — Verify installation

```bash
curl "http://127.0.0.1:8000/api/skills/catalog"
```

Your skill should appear in the list.

---

## Step 7 — Activate and use the skill

### Via API

```bash
curl -X POST http://127.0.0.1:8000/api/skills/activate \
  -H "Content-Type: application/json" \
  -d '{"skill_id": "my_skill", "session_id": "s1", "user_id": "u1"}'
```

### Via chat request

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "Help me with X",
    "session_id": "s1",
    "user_id": "u1",
    "requested_skill": "my_skill",
    "requested_mode": "fast"
  }'
```

---

## Step 8 — Add evaluation cases (optional but recommended)

```json
[
  {
    "input": "Do X with the following: ...",
    "expected_tool_calls": ["workspace.write_document"],
    "expected_output_contains": ["X was completed"],
    "tags": ["happy_path"]
  }
]
```

Save to `skills/packs/official/my_skill/examples.json`.

---

## Checklist

- [ ] `skill.yaml` with valid `skill_id` and `default_mode`
- [ ] `system_instruction.md` written
- [ ] `tool_allowlist.yaml` written (or set `allowed_tools: ["*"]`)
- [ ] Skill registered in `skills/registry.py`
- [ ] Appears in `/api/skills/catalog`
- [ ] `examples.json` added (optional)

---

## What you do NOT need to change

- `gateway/conversation_pipeline.py` — skill is injected automatically via `RunContext`
- `gateway/tool_service.py` — tool allowlist is applied via `ToolPolicy`
- Any memory backend
