from __future__ import annotations

from typing import Dict, Set


PENDING = "pending"
RUNNING = "running"
WAITING_TOOL = "waiting_tool"
WAITING_HUMAN = "waiting_human"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"

TERMINAL_STATES: Set[str] = {SUCCEEDED, FAILED, SKIPPED}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    PENDING: {RUNNING, SKIPPED, FAILED},
    RUNNING: {WAITING_TOOL, WAITING_HUMAN, SUCCEEDED, FAILED, SKIPPED},
    WAITING_TOOL: {RUNNING, FAILED},
    WAITING_HUMAN: {RUNNING, FAILED, SKIPPED},
    SUCCEEDED: set(),
    FAILED: set(),
    SKIPPED: set(),
}


def can_transition(current: str, target: str) -> bool:
    allowed = ALLOWED_TRANSITIONS.get(str(current or "").strip(), set())
    return str(target or "").strip() in allowed
