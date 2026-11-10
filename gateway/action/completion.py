"""Non-executing completion at a boundary where tool dispatch is disabled."""
from __future__ import annotations

from .model_action import InvalidModelAction, ModelAction, parse_model_action


def parse_final_answer(content: str) -> ModelAction:
    text = str(content or "").strip()
    if not text:
        raise InvalidModelAction("model returned no final answer")
    # Structured instructions must never become user-facing prose or execute here.
    if text.startswith(("{", "[", "<", "```")):
        action = parse_model_action(text)
        if action.kind not in {"answer", "await_user"}:
            raise InvalidModelAction("execution is disabled during final completion")
        return action
    return ModelAction(kind="answer", content=text)


def runtime_progress_notice(observations: list[dict], language: str = "en", *, stop_reason: str = "budget_exhausted", completion_code: str = "") -> str:
    settled = [row for row in observations if not str(row.get("tool_name", "")).startswith("runtime.")]
    successful = [row for row in settled if row.get("ok") is True]
    failed = len(settled) - len(successful)
    lines = [
        f"Runtime: execution stopped ({stop_reason}); the final model response was unavailable.",
        "Goal completion is unverified. Committed results and artifacts have been retained.",
        f"Tool observations: {len(successful)} succeeded, {failed} failed.",
    ]
    if language.lower().startswith("zh"):
        lines = [
            "\u8fd0\u884c\u72b6\u6001\uff1a\u672c\u8f6e\u6267\u884c\u9884\u7b97\u5df2\u7528\u5c3d\uff0c\u6700\u7ec8\u6a21\u578b\u56de\u590d\u4e0d\u53ef\u7528\u3002",
            "\u76ee\u6807\u5b8c\u6210\u60c5\u51b5\u5c1a\u672a\u9a8c\u8bc1\uff1b\u5df2\u63d0\u4ea4\u7684\u7ed3\u679c\u548c\u4ea7\u7269\u5df2\u4fdd\u7559\u3002",
            f"\u5de5\u5177\u89c2\u5bdf\u8bb0\u5f55\uff1a{len(successful)} \u9879\u6210\u529f\uff0c{failed} \u9879\u5931\u8d25\u3002",
        ]
        if stop_reason == "recovery_exhausted":
            lines[0] = "\u8fd0\u884c\u72b6\u6001\uff1a\u672c\u8f6e\u6062\u590d\u5c1d\u8bd5\u5df2\u8fbe\u5230\u4e0a\u9650\uff0c\u6700\u7ec8\u6a21\u578b\u56de\u590d\u4e0d\u53ef\u7528\u3002"
        if completion_code == "MODEL_ADMISSION_CLOSED":
            lines[0] = "\u8fd0\u884c\u72b6\u6001\uff1a\u6a21\u578b\u8bf7\u6c42\u5df2\u6682\u505c\uff0c\u672a\u53d1\u9001\u65b0\u7684\u8bf7\u6c42\u3002"
        elif completion_code == "MODEL_REQUEST_FAILED":
            lines[0] = "\u8fd0\u884c\u72b6\u6001\uff1a\u6a21\u578b\u670d\u52a1\u8bf7\u6c42\u5931\u8d25\uff0c\u6700\u7ec8\u6a21\u578b\u56de\u590d\u4e0d\u53ef\u7528\u3002"
    elif completion_code == "MODEL_ADMISSION_CLOSED":
        lines[0] = "Runtime: model requests are paused; no further request was sent."
    elif completion_code == "MODEL_REQUEST_FAILED":
        lines[0] = "Runtime: the model provider request failed; the final model response was unavailable."
    for row in successful:
        value = row.get("structured_result")
        path = value.get("path") if isinstance(value, dict) else None
        if isinstance(path, str):
            lines.append(f"- {path}")
    return "\n".join(lines)
