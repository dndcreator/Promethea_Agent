"""Canonical execution-time result for tools and MCP adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ContentBlock = Dict[str, Any]


@dataclass(frozen=True)
class ToolErrorInfo:
    code: str
    message: str
    category: str = "tool"
    retryable: bool = False
    advice: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "retryable": self.retryable,
        }
        if self.advice:
            payload["advice"] = self.advice
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    ok: bool
    value: Any = None
    content: List[ContentBlock] = field(default_factory=list)
    error: Optional[ToolErrorInfo] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("successful tool result cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("failed tool result requires an error")

    def event_fields(self) -> Dict[str, Any]:
        fields = {
            "ok": self.ok,
            "status": "completed" if self.ok else "failed",
            "error_detail": self.error.as_dict() if self.error else None,
            "result_summary": summarize_value(self.value) if self.ok else None,
        }
        if self.metadata:
            fields["result_metadata"] = dict(self.metadata)
        return fields


def error_from_exception(exc: BaseException) -> ToolErrorInfo:
    message = str(exc) or exc.__class__.__name__
    explicit_code = str(getattr(exc, "code", "") or "").strip().upper()
    if explicit_code:
        return ToolErrorInfo(
            code=explicit_code,
            message=message,
            category=str(getattr(exc, "category", "tool") or "tool"),
            retryable=bool(getattr(exc, "retryable", False)),
            advice=str(getattr(exc, "advice", "") or "") or None,
            details=dict(getattr(exc, "details", {}) or {}),
        )
    if isinstance(exc, FileNotFoundError):
        return ToolErrorInfo("FS_NOT_FOUND", message, "filesystem", True)
    if isinstance(exc, PermissionError):
        return ToolErrorInfo("FS_PERMISSION_DENIED", message, "filesystem", False)
    if isinstance(exc, (ValueError, TypeError)):
        return ToolErrorInfo("INVALID_ARGS", message, "validation", True)
    if isinstance(exc, TimeoutError):
        return ToolErrorInfo("TOOL_TIMEOUT", message, "timeout", True)
    return ToolErrorInfo("TOOL_EXECUTION_FAILED", message, "tool", False)


def normalize_tool_result(tool_name: str, raw: Any) -> ToolExecutionResult:
    """Normalize first-party, legacy string, and MCP results without changing their value."""
    if isinstance(raw, ToolExecutionResult):
        return raw

    mcp_error = getattr(raw, "isError", None)
    if mcp_error is None:
        mcp_error = getattr(raw, "is_error", None)
    if mcp_error is not None and hasattr(raw, "content"):
        blocks = _normalize_content_blocks(getattr(raw, "content", None))
        value = getattr(raw, "structuredContent", None)
        if value is None:
            value = getattr(raw, "structured_content", None)
        if bool(mcp_error):
            message = _content_text(blocks) or "MCP tool reported an error"
            error = _error_from_message(message, default_code="MCP_TOOL_ERROR")
            return ToolExecutionResult(tool_name, False, content=blocks, error=error)
        return ToolExecutionResult(tool_name, True, value=value, content=blocks)

    failure = _failure_from_value(raw)
    if failure is not None:
        return ToolExecutionResult(
            tool_name=tool_name,
            ok=False,
            value=None,
            content=_render_content(tool_name, raw),
            error=failure,
        )

    return ToolExecutionResult(
        tool_name=tool_name,
        ok=True,
        value=raw,
        content=_render_content(tool_name, raw),
    )


def failed_tool_result(tool_name: str, exc: BaseException) -> ToolExecutionResult:
    error = error_from_exception(exc)
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=False,
        content=[{"type": "text", "text": f'Result from tool "{tool_name}"\n[Error] {error.message}'}],
        error=error,
    )


def summarize_value(value: Any, max_chars: int = 500) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "..."
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())[:20], "size": len(value)}
    if isinstance(value, (list, tuple, set)):
        return {"type": "array", "size": len(value)}
    return {"type": value.__class__.__name__}


def _failure_from_value(raw: Any) -> Optional[ToolErrorInfo]:
    if isinstance(raw, dict):
        explicit_ok = raw.get("ok")
        explicit_success = raw.get("success")
        status = str(raw.get("status") or "").strip().lower()
        error_value = raw.get("error_detail") or raw.get("error")
        failed = explicit_ok is False or explicit_success is False or status in {
            "error", "failed", "failure", "unavailable", "denied",
        }
        if error_value and explicit_ok is not True and explicit_success is not True and status not in {
            "ok", "success", "completed",
        }:
            failed = True
        if failed:
            if isinstance(error_value, dict):
                message = str(error_value.get("message") or error_value.get("error") or "Tool call failed")
                code = str(error_value.get("code") or "TOOL_REPORTED_ERROR")
                return ToolErrorInfo(
                    code=code,
                    message=message,
                    category=str(error_value.get("category") or "tool"),
                    retryable=bool(error_value.get("retryable", False)),
                    advice=str(error_value.get("advice") or "") or None,
                    details=dict(error_value.get("details") or {}),
                )
            return _error_from_message(str(error_value or raw.get("message") or "Tool call failed"))
        return None

    if isinstance(raw, str):
        # Compatibility ends here. New tools must report structured status;
        # routing and projections never infer outcomes from display text.
        text = raw.strip()
        lowered = text.lower()
        if lowered.startswith(("error:", "[error]", "call failed:", "error executing tool", "tool execution error:")):
            return _error_from_message(text)
    return None


def _error_from_message(message: str, default_code: str = "TOOL_REPORTED_ERROR") -> ToolErrorInfo:
    lowered = message.lower()
    if "not found" in lowered or "does not exist" in lowered:
        return ToolErrorInfo("FS_NOT_FOUND", message, "filesystem", True)
    if "not initialized" in lowered or "unavailable" in lowered or "dependency" in lowered:
        return ToolErrorInfo("CAPABILITY_UNAVAILABLE", message, "capability", True)
    if "permission" in lowered or "access denied" in lowered or "forbidden" in lowered:
        return ToolErrorInfo("PERMISSION_DENIED", message, "policy", False)
    if "timeout" in lowered or "timed out" in lowered:
        return ToolErrorInfo("TOOL_TIMEOUT", message, "timeout", True)
    return ToolErrorInfo(default_code, message, "tool", False)


def _render_content(tool_name: str, value: Any) -> List[ContentBlock]:
    import json

    header = f'Result from tool "{tool_name}"'
    images: List[str] = []
    display = value
    if isinstance(value, dict):
        display = dict(value)
        for key in ("screenshot", "base64"):
            blob = display.get(key)
            if blob:
                images.append(str(blob))
                display[key] = "<image_base64_hidden>"
        text = json.dumps(_json_safe(display), ensure_ascii=False, indent=2)
    else:
        text = str(value)
    blocks: List[ContentBlock] = [{"type": "text", "text": f"{header}\n{text}"}]
    blocks.extend(
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{blob}"}}
        for blob in images
    )
    return blocks


def _normalize_content_blocks(content: Any) -> List[ContentBlock]:
    blocks: List[ContentBlock] = []
    for block in content or []:
        if isinstance(block, dict):
            blocks.append(dict(block))
            continue
        block_type = str(getattr(block, "type", "text") or "text")
        if block_type == "text":
            blocks.append({"type": "text", "text": str(getattr(block, "text", "") or "")})
    return blocks


def _content_text(blocks: List[ContentBlock]) -> str:
    return "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if block.get("type") == "text"
    ).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return str(value)
