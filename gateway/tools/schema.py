from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def text(*, enum: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "string"}
    if enum is not None:
        schema["enum"] = [str(item) for item in enum]
    return schema


def integer(*, minimum: Optional[int] = None, maximum: Optional[int] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "integer"}
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def boolean() -> Dict[str, Any]:
    return {"type": "boolean"}


def array(items: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"type": "array", "items": dict(items or {})}


def object_value() -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": True}


def input_object(
    properties: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    required: Iterable[str] = (),
) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": [str(item) for item in required],
        "additionalProperties": False,
    }
