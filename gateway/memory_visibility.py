from __future__ import annotations

from typing import Any, Dict, List

from .protocol import MemoryRecallBundle


def build_memory_visibility(
    *,
    memory_bundle: MemoryRecallBundle,
    feedback_hints: List[Dict[str, Any]],
) -> Dict[str, Any]:
    notices: List[str] = []
    recall_notice = ""
    if memory_bundle.recalled:
        snippet = _extract_recall_snippet(memory_bundle.context)
        recall_notice = (
            f"我参考了你的历史记忆：{snippet}"
            if snippet
            else "我参考了你的历史记忆来回答。"
        )
        notices.append(recall_notice)

    saved_rows = [
        row
        for row in (feedback_hints or [])
        if str((row or {}).get("type", "")) == "memory_saved"
    ]
    review_rows = [
        row
        for row in (feedback_hints or [])
        if str((row or {}).get("type", "")) == "memory_review_needed"
    ]
    write_notice = ""
    review_notice = ""
    if saved_rows:
        mt = str(saved_rows[-1].get("memory_type") or "记忆")
        write_notice = f"已记住你的一条{mt}信息。"
        notices.append(write_notice)
    if review_rows:
        mt = str(review_rows[-1].get("memory_type") or "记忆")
        review_notice = f"检测到{mt}冲突，待你确认后再写入。"
        notices.append(review_notice)

    return {
        "enabled": bool(memory_bundle.recalled or feedback_hints),
        "recalled": bool(memory_bundle.recalled),
        "recall_notice": recall_notice,
        "write_notice": write_notice,
        "review_notice": review_notice,
        "feedback_hints": list(feedback_hints or []),
        "notices": notices,
    }


def _extract_recall_snippet(context: str, *, max_chars: int = 80) -> str:
    text = str(context or "").strip()
    if not text:
        return ""
    lines = [
        ln.strip("- ").strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("[")
    ]
    if not lines:
        return ""
    snippet = lines[0].replace("\n", " ").strip()
    if len(snippet) > max_chars:
        snippet = snippet[: max(1, int(max_chars) - 3)] + "..."
    return snippet
