"""Invocation-scoped consent issued only by the Runtime confirmation path."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


def _subject(name: str, args: dict[str, Any]) -> str:
    return json.dumps([name, args], sort_keys=True, ensure_ascii=True, separators=(",", ":"))


@dataclass
class _Approval:
    subject: str
    confirmed: bool
    active: bool = True


_current: ContextVar[_Approval | None] = ContextVar("tool_approval", default=None)


def call_is_approved() -> bool:
    grant = _current.get()
    return grant is not None and grant.active and grant.confirmed


def matches_approved_call(name: str, args: dict[str, Any]) -> bool:
    grant = _current.get()
    return call_is_approved() and grant.subject == _subject(name, args)


@contextmanager
def approval_scope(name: str, args: dict[str, Any], *, confirmed: bool = False):
    grant = _Approval(_subject(name, args), confirmed)
    token = _current.set(grant)
    try:
        yield
    finally:
        # Child tasks inherit the object, so resetting a ContextVar alone would
        # leave a usable grant in a task that outlives its approved invocation.
        grant.active = False
        _current.reset(token)
