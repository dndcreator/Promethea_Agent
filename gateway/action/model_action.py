from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass(frozen=True)
class ToolCallProposal:
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex}")


@dataclass(frozen=True)
class CapabilityRequest:
    objective: str
    required_capabilities: List[str]
    max_side_effect: str = "read_only"
    preferred_modalities: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelAction:
    kind: Literal["answer", "tool_calls", "capability_inspect", "capability_request"]
    content: str = ""
    calls: List[ToolCallProposal] = field(default_factory=list)
    capability_names: List[str] = field(default_factory=list)
    capability_request: Optional[CapabilityRequest] = None
    evidence_refs: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


class InvalidModelAction(ValueError):
    code = "INVALID_MODEL_ACTION"


class AnswerDeltaProjector:
    """Projects text replies while keeping internal action envelopes private."""

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted = ""
        self._mode: Optional[Literal["action", "invalid"]] = None

    def feed(self, chunk: str) -> str:
        self._buffer += str(chunk or "")
        if self._mode is None:
            stripped = self._buffer.lstrip()
            if not stripped:
                return ""
            self._mode = "action" if stripped.startswith("{") else "invalid"
        if self._mode == "invalid":
            return ""
        fields = _root_string_fields(self._buffer)
        action, action_complete = fields.get("action", ("", False))
        if not action_complete or action.strip().lower() != "answer":
            return ""
        content, _ = fields.get("content", fields.get("answer", ("", False)))
        if not content.startswith(self._emitted):
            return ""
        delta = content[len(self._emitted) :]
        self._emitted = content
        return delta


def _root_string_fields(text: str) -> Dict[str, tuple[str, bool]]:
    """Walk root members with the standard decoder; nested values stay opaque."""
    decoder = json.JSONDecoder()
    fields: Dict[str, tuple[str, bool]] = {}
    index = len(text) - len(text.lstrip())
    if index >= len(text) or text[index] != "{":
        return fields
    index += 1
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        try:
            key, index = decoder.raw_decode(text, index)
            if not isinstance(key, str) or key in fields:
                return {}
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text) or text[index] != ":":
                return fields
            index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                return fields
            if text[index] == '"':
                prefix, complete = _json_string_prefix(text[index + 1:])
                fields[key] = (prefix, complete)
                if not complete:
                    return fields
            _, index = decoder.raw_decode(text, index)
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text) or text[index] != ",":
                return fields
            index += 1
        except (json.JSONDecodeError, ValueError):
            return fields
    return fields


def _json_string_prefix(source: str) -> tuple[str, bool]:
    decoded: List[str] = []
    index = 0
    escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while index < len(source):
        char = source[index]
        if char == '"':
            return "".join(decoded), True
        if char != "\\":
            if ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF:
                break
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(source):
            break
        escaped = source[index + 1]
        if escaped == "u":
            digits = source[index + 2 : index + 6]
            if len(digits) < 4 or any(item not in "0123456789abcdefABCDEF" for item in digits):
                break
            codepoint = int(digits, 16)
            if 0xD800 <= codepoint <= 0xDBFF:
                low_prefix = source[index + 6 : index + 8]
                low_digits = source[index + 8 : index + 12]
                if low_prefix != "\\u" or len(low_digits) < 4 or any(
                    item not in "0123456789abcdefABCDEF" for item in low_digits
                ):
                    break
                low = int(low_digits, 16)
                if not 0xDC00 <= low <= 0xDFFF:
                    break
                decoded.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)))
                index += 12
                continue
            if 0xDC00 <= codepoint <= 0xDFFF:
                break
            decoded.append(chr(codepoint))
            index += 6
            continue
        if escaped not in escapes:
            break
        decoded.append(escapes[escaped])
        index += 2
    return "".join(decoded), False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidModelAction("duplicate runtime action fields")
        result[key] = value
    return result


def parse_model_action(content: str) -> ModelAction:
    text = str(content or "").strip()
    if not text:
        raise InvalidModelAction("model returned no assistant content")
    try:
        parsed = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise InvalidModelAction("model returned a non-canonical runtime action") from exc
    if not isinstance(parsed, dict):
        raise InvalidModelAction("runtime action must be a JSON object")
    raw = dict(parsed)
    procedure_refs = raw.get("procedure_refs", [])
    if not isinstance(procedure_refs, list) or any(not isinstance(ref, str) for ref in procedure_refs):
        raise InvalidModelAction("procedure_refs must be an array of versioned rule references")
    action = str(raw.get("action") or "").strip().lower()
    if not action:
        raise InvalidModelAction("runtime action type is required")
    if action == "answer":
        answer = raw.get("content", raw.get("answer", ""))
        if not isinstance(answer, str) or not answer.strip():
            raise InvalidModelAction("answer content must be non-empty text")
        refs = raw.get("evidence_refs") or []
        if not isinstance(refs, list):
            raise InvalidModelAction("answer evidence_refs must be an array")
        return ModelAction(
            kind="answer",
            content=str(answer or ""),
            evidence_refs=[str(item) for item in refs if str(item).strip()],
            raw=raw,
        )
    if action in {"tool_call", "tool_calls"}:
        source_calls = raw.get("calls") if action == "tool_calls" else [raw]
        if not isinstance(source_calls, list) or not source_calls:
            raise InvalidModelAction("tool_calls requires a non-empty calls array")
        calls: List[ToolCallProposal] = []
        for item in source_calls:
            if not isinstance(item, dict):
                raise InvalidModelAction("each tool call must be an object")
            name = str(item.get("tool_name") or item.get("name") or "").strip()
            arguments = item.get("args", item.get("arguments", {}))
            if not name:
                raise InvalidModelAction("tool_name is required")
            if not isinstance(arguments, dict):
                raise InvalidModelAction("tool args must be an object")
            calls.append(
                ToolCallProposal(
                    tool_name=name,
                    arguments=dict(arguments),
                    call_id=str(item.get("id") or item.get("call_id") or f"call_{uuid.uuid4().hex}"),
                )
            )
        if len({call.call_id for call in calls}) != len(calls):
            raise InvalidModelAction("tool call ids must be unique within a batch")
        return ModelAction(kind="tool_calls", calls=calls, raw=raw)
    if action == "capability_inspect":
        names = raw.get("capability_names") or raw.get("names") or []
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or not names:
            raise InvalidModelAction("capability_inspect requires capability_names")
        return ModelAction(
            kind="capability_inspect",
            capability_names=[str(item) for item in names if str(item).strip()],
            raw=raw,
        )
    if action == "capability_request":
        objective = str(raw.get("objective") or "").strip()
        required = raw.get("required_capabilities") or []
        modalities = raw.get("preferred_modalities") or []
        if isinstance(required, str):
            required = [required]
        if isinstance(modalities, str):
            modalities = [modalities]
        if not objective:
            raise InvalidModelAction("capability_request requires objective")
        if not isinstance(required, list) or not any(str(item).strip() for item in required):
            raise InvalidModelAction("capability_request requires required_capabilities")
        if not isinstance(modalities, list):
            raise InvalidModelAction("capability_request preferred_modalities must be an array")
        max_side_effect = str(raw.get("max_side_effect") or "read_only").strip().lower()
        if max_side_effect not in {
            "read_only",
            "workspace_write",
            "external_write",
            "privileged_host_action",
        }:
            raise InvalidModelAction("capability_request max_side_effect is invalid")
        return ModelAction(
            kind="capability_request",
            capability_request=CapabilityRequest(
                objective=objective,
                required_capabilities=[str(item).strip() for item in required if str(item).strip()],
                max_side_effect=max_side_effect,
                preferred_modalities=[str(item).strip() for item in modalities if str(item).strip()],
            ),
            raw=raw,
        )
    raise InvalidModelAction(f"unsupported model action: {action or '<missing>'}")
