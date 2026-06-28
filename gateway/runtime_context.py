from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Asia/Shanghai"


def build_runtime_clock(*, timezone_name: str = DEFAULT_TIMEZONE) -> Dict[str, str]:
    """Return a compact, timezone-aware clock snapshot for runtime prompts."""
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        # Windows/minimal Python distributions may not ship IANA tzdata.
        # Keep the runtime clock available instead of failing conversation setup.
        tz = timezone(timedelta(hours=8), name=DEFAULT_TIMEZONE)
        timezone_name = DEFAULT_TIMEZONE
    now = datetime.now(tz)
    return {
        "timezone": timezone_name,
        "local_date": now.date().isoformat(),
        "local_time": now.strftime("%H:%M:%S"),
        "local_datetime": now.isoformat(timespec="seconds"),
    }


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
    timezone_name: str = DEFAULT_TIMEZONE,
) -> str:
    """Build the shared runtime-context block used by routing and answering."""
    clock = build_runtime_clock(timezone_name=timezone_name)
    recent_text = format_recent_messages(recent_messages)
    sections = [
        "Runtime context:",
        f"- Current local date: {clock['local_date']}",
        f"- Current local time: {clock['local_time']} ({clock['timezone']})",
        f"- Current local datetime: {clock['local_datetime']}",
        "- Resolve short follow-ups and ellipses against the recent conversation when present.",
        "- For current/latest/recent external facts, use runtime observations from tools; do not infer stale dates.",
        "- Do not claim that a search, tool call, file read/write, browser action, or external lookup happened unless a runtime Observation/result exists in this turn.",
    ]
    if recent_text:
        sections.extend(["Recent conversation:", recent_text])
    return "\n".join(sections)
