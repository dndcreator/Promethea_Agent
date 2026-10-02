from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .temporal import clock_snapshot, resolve_context_timezone_name


def build_runtime_clock(
    *,
    timezone_name: str = "",
    user_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Return a compact, timezone-aware clock snapshot for runtime prompts."""
    resolved = resolve_context_timezone_name(user_config, timezone_name)
    return clock_snapshot(requested_timezone=resolved)


def format_recent_messages(
    recent_messages: Optional[Iterable[Dict[str, Any]]],
    *,
    limit: int = 6,
    max_chars_per_message: int = 700,
) -> str:
    rows: List[str] = []
    for message in list(recent_messages or [])[-limit:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown").strip() or "unknown"
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if len(content) > max_chars_per_message:
            content = content[: max_chars_per_message - 1].rstrip() + "..."
        rows.append(f"- {role}: {content}")
    return "\n".join(rows)


def build_runtime_context_block(
    *,
    recent_messages: Optional[Iterable[Dict[str, Any]]] = None,
    timezone_name: str = "",
    user_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the shared runtime-context block used by routing and answering."""
    clock = build_runtime_clock(timezone_name=timezone_name, user_config=user_config)
    # Recent conversation is owned by the policy/router or the message list.
    # Keeping it here duplicated model-visible context and token usage.
    _ = recent_messages
    sections = [
        "Runtime context:",
        f"- Current local date: {clock['local_date']}",
        f"- Current local time: {clock['local_time']} ({clock['timezone']})",
        f"- Current local datetime: {clock['local_datetime']}",
        "- Resolve short follow-ups and ellipses against the recent conversation when present.",
        "- For current/latest/recent external facts, use runtime observations from tools; do not infer stale dates.",
        "- Do not claim that a search, tool call, file read/write, browser action, or external lookup happened unless a runtime Observation/result exists in this turn.",
    ]
    return "\n".join(sections)
