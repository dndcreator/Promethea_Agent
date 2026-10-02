"""Trusted workspace identity propagated by the Runtime, never tool arguments."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path


@dataclass(frozen=True)
class ComputerWorkspace:
    user_id: str
    workspace_id: str
    root: Path
    execution: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


_current: ContextVar[ComputerWorkspace | None] = ContextVar("computer_workspace", default=None)


def current_workspace() -> ComputerWorkspace | None:
    return _current.get()


@contextmanager
def bind_workspace(handle, execution: dict[str, Any] | None = None):
    scope = ComputerWorkspace(
        str(handle.user_id),
        str(handle.workspace_id),
        Path(handle.root_path).resolve(),
        dict(execution or {}),
    )
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
