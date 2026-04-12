from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def truncate_text(text: str, limit: int) -> str:
    if len(text or "") <= limit:
        return text or ""
    return (text or "")[: limit - 3] + "..."


def format_recent_messages(messages: List[Dict[str, Any]], *, keep_last: int = 6, content_limit: int = 300) -> str:
    if not messages:
        return "(none)"
    formatted = []
    for item in messages[-max(1, int(keep_last)) :]:
        role = item.get("role", "unknown")
        content = truncate_text(str(item.get("content", "")), max(1, int(content_limit)))
        formatted.append(f"{role}: {content}")
    return "\n".join(formatted)


def stringify_observation(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


def to_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off", ""}:
            return False
        return default
    return bool(value)


def merge_steps(
    template_steps: List[Dict[str, Any]],
    generated_steps: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in (template_steps or []) + (generated_steps or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().lower()
        goal = str(item.get("goal", "")).strip().lower()
        key = (title, goal)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max(1, int(limit)):
            break
    return merged


def map_plan_steps_to_moirai(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mapped: List[Dict[str, Any]] = []
    for i, item in enumerate(steps or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"Plan Step {i + 1}").strip() or f"Plan Step {i + 1}"
        goal = str(item.get("goal") or title).strip() or title
        requires_tools = to_bool(item.get("requires_tools"), default=False)
        tool_intent = str(item.get("tool_intent") or "").strip()

        mapped.append(
            {
                "id": f"plan_{i + 1}",
                "name": title,
                "kind": "note",
                "params": {
                    "text": goal,
                    "source_step": item,
                },
            }
        )

        if requires_tools:
            mapped.append(
                {
                    "id": f"plan_{i + 1}_tool_probe",
                    "name": f"Tool probe: {title}",
                    "kind": "mcp_call",
                    "require_approval": True,
                    "continue_on_error": True,
                    "params": {
                        "service_name": "computer_control",
                        "tool_name": "execute_command",
                        "args": {
                            "command": "echo [Moirai tool probe] " + (tool_intent or goal),
                        },
                    },
                }
            )
    return mapped


def safe_user_segment(user_id: Optional[str]) -> str:
    uid = str(user_id or "default_user").strip() or "default_user"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
    return safe[:128] or "default_user"
