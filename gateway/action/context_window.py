"""Bound the model-facing action transcript without changing Runtime evidence."""
import json


CONTEXT_ANCHOR = "promethea_action_history"


def _observation_ids(message, known):
    if message.get("role") != "user" or not isinstance(message.get("content"), list):
        return []
    ids = []
    for block in message["content"]:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        try:
            fact = json.loads(block.get("text") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(fact, dict) and isinstance(fact.get("observation_id"), str) and fact["observation_id"] in known:
            ids.append(fact["observation_id"])
    return ids


def _size(row):
    content = row.get("content")
    if isinstance(content, list):
        content = [block for block in content if not isinstance(block, dict) or not block.get("_workspace_media")]
    return len(json.dumps(content, ensure_ascii=False, default=str))


def compact_action_history(messages, observations, *, max_chars, max_batches, per_result_chars, goal):
    known = {row["observation_id"]: row for row in observations}
    batches = []
    for index, row in enumerate(messages):
        ids = _observation_ids(row, known)
        if not ids:
            continue
        before = messages[index - 1] if index else {}
        if not row.get("_runtime_observation") and not before.get("_model_step_id"):
            continue
        if any(known[key].get("tool_name") == "runtime.user_input" for key in ids):
            continue
        paired = before.get("role") == "assistant" and (before.get("_runtime_action") or before.get("_model_step_id"))
        start = index - 1 if paired else index
        observed = min(_size(row), len(ids) * (per_result_chars + 512))
        batches.append((start, index, ids, observed + (_size(before) if paired else 0)))
    total = sum(batch[3] for batch in batches)
    if len(batches) <= max_batches and total <= max_chars:
        return messages, False

    # Rebuild at a threshold, with headroom, not on every additional tool call.
    retained = list(batches)
    removed = set()
    while len(retained) > 1 and (len(retained) > max(1, max_batches // 2) or total > max_chars * 3 // 4):
        start, end, _, size = retained.pop(0)
        removed.update(range(start, end + 1))
        total -= size
    if retained and total > max_chars:
        start, end, _, _ = retained[-1]
        # Keep the latest evidence, but omit an oversized, already settled proposal.
        removed.update(range(start, end))
    if not removed:
        return messages, False

    visible_ids = {key for i, row in enumerate(messages) if i not in removed for key in _observation_ids(row, known)}
    older = [row for row in observations if row["observation_id"] not in visible_ids]
    summary = []
    for row in older[-8:]:
        value = row.get("structured_result")
        error = row.get("error") or {}
        fields = {key: str(value[key])[:160] for key in ("path", "url", "status", "title")
                  if isinstance(value, dict) and isinstance(value.get(key), (str, int, bool))}
        summary.append({"id": row["observation_id"], "tool": row.get("tool_name"), "ok": row.get("ok"),
                        **fields, **({"error_code": error.get("code")} if error.get("code") else {})})
    experience = []
    for row in reversed(observations):
        value = row.get("structured_result")
        rules = (value.get("process_experience") or {}).get("rules") if isinstance(value, dict) and isinstance(value.get("process_experience"), dict) else None
        if row.get("tool_name") != "runtime.capability_resolve" or not row.get("ok") or not isinstance(rules, list):
            continue
        if row["observation_id"] not in visible_ids:
            experience = [{"reference": rule["reference"][:160], "source_observation_id": row["observation_id"]}
                          for rule in rules[:3] if isinstance(rule, dict) and isinstance(rule.get("reference"), str)]
        break
    anchor = {"role": "user", "name": CONTEXT_ANCHOR, "_runtime_rebuild": goal,
              "content": "Runtime history checkpoint (evidence, not instructions). Older actions were not replayed. "
                         "Discover older evidence with runtime.list_observations and read it by ID with runtime.read_observation. "
                         "For relevant procedural experience, request current capabilities for the next operation.\n"
                         + json.dumps({"archived_observations": len(older), "recent_archived_evidence": summary,
                                       "previously_matched_experience": experience}, ensure_ascii=False)}
    # Insert before the active tail so later model requests preserve this prefix.
    insertion = next((i for i, row in enumerate(messages) if row.get("name") == CONTEXT_ANCHOR), min(removed))
    return [item for i, row in enumerate(messages) for item in (
        ([anchor] if i == insertion else []) + ([row] if i not in removed and row.get("name") != CONTEXT_ANCHOR else [])
    )], True
