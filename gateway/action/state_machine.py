from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Set


class ActionPhase(str, Enum):
    """Runtime-owned lifecycle for one model/tool control loop."""

    PENDING = "pending"
    AWAITING_MODEL = "awaiting_model"
    EVALUATING = "evaluating"
    VALIDATING = "validating"
    EXECUTING = "executing"
    WAITING_CONFIRMATION = "waiting_confirmation"
    OBSERVING = "observing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_PHASES: Set[ActionPhase] = {
    ActionPhase.WAITING_CONFIRMATION,
    ActionPhase.COMPLETED,
    ActionPhase.FAILED,
    ActionPhase.CANCELLED,
}


_ALLOWED: Mapping[ActionPhase, Set[ActionPhase]] = {
    ActionPhase.PENDING: {ActionPhase.AWAITING_MODEL, ActionPhase.FAILED, ActionPhase.CANCELLED},
    ActionPhase.AWAITING_MODEL: {ActionPhase.EVALUATING, ActionPhase.FAILED, ActionPhase.CANCELLED},
    ActionPhase.EVALUATING: {
        ActionPhase.AWAITING_MODEL,
        ActionPhase.VALIDATING,
        ActionPhase.COMPLETED,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
    ActionPhase.VALIDATING: {
        ActionPhase.EXECUTING,
        ActionPhase.WAITING_CONFIRMATION,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
    ActionPhase.EXECUTING: {
        ActionPhase.EXECUTING,
        ActionPhase.OBSERVING,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
    ActionPhase.OBSERVING: {
        ActionPhase.AWAITING_MODEL,
        ActionPhase.COMPLETED,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
    ActionPhase.WAITING_CONFIRMATION: set(),
    ActionPhase.COMPLETED: set(),
    ActionPhase.FAILED: set(),
    ActionPhase.CANCELLED: set(),
}


class InvalidActionTransition(RuntimeError):
    pass


@dataclass
class RuntimeActionStateMachine:
    """Validates and records state transitions committed by the runtime."""

    phase: ActionPhase = ActionPhase.PENDING
    revision: int = 0
    transitions: List[Dict[str, Any]] = field(default_factory=list)

    def transition(
        self,
        target: ActionPhase,
        *,
        cause: str,
        facts: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if target not in _ALLOWED[self.phase]:
            raise InvalidActionTransition(
                f"invalid action transition: {self.phase.value} -> {target.value} ({cause})"
            )
        previous = self.phase
        self.phase = target
        self.revision += 1
        record = {
            "revision": self.revision,
            "from": previous.value,
            "to": target.value,
            "cause": str(cause),
            "facts": dict(facts or {}),
            "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self.transitions.append(record)
        return record

    def snapshot(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "revision": self.revision,
            "terminal": self.phase in TERMINAL_PHASES,
        }

