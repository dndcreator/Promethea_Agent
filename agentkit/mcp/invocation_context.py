"""Trusted context propagated across a single tool invocation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Mapping


_INVOCATION_CONTEXT: ContextVar[Dict[str, Any]] = ContextVar(
    "promethea_tool_invocation_context",
    default={},
)


def get_invocation_context() -> Dict[str, Any]:
    return dict(_INVOCATION_CONTEXT.get())


@contextmanager
def bind_invocation_context(fields: Mapping[str, Any] | None) -> Iterator[Dict[str, Any]]:
    current = get_invocation_context()
    current.update({str(key): value for key, value in dict(fields or {}).items() if value is not None})
    token = _INVOCATION_CONTEXT.set(current)
    try:
        yield current
    finally:
        _INVOCATION_CONTEXT.reset(token)
