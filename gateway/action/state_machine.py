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
    ActionPhase.COMPLETED,
    ActionPhase.FAILED,
    ActionPhase.CANCELLED,
}


_ALLOWED: Mapping[ActionPhase, Set[ActionPhase]] = {
    ActionPhase.PENDING: {ActionPhase.AWAITING_MODEL, ActionPhase.FAILED, ActionPhase.CANCELLED},
    ActionPhase.AWAITING_MODEL: {ActionPhase.EVALUATING, ActionPhase.OBSERVING, ActionPhase.FAILED, ActionPhase.CANCELLED},
    ActionPhase.EVALUATING: {
        ActionPhase.AWAITING_MODEL,
        ActionPhase.OBSERVING,
        ActionPhase.VALIDATING,
        ActionPhase.COMPLETED,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
    ActionPhase.VALIDATING: {
        ActionPhase.EXECUTING,
        ActionPhase.OBSERVING,
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
    ActionPhase.WAITING_CONFIRMATION: {
        ActionPhase.VALIDATING,
        ActionPhase.OBSERVING,
        ActionPhase.FAILED,
        ActionPhase.CANCELLED,
    },
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

    @classmethod
    def restore(cls, transitions: List[Dict[str, Any]]) -> "RuntimeActionStateMachine":
        machine = cls()
        for index, row in enumerate(transitions or [], start=1):
            declared_from = str(row.get("from") or "")
            if declared_from and declared_from != machine.phase.value:
                raise InvalidActionTransition(
                    f"invalid restored transition source: expected {machine.phase.value}, got {declared_from}"
                )
            declared_revision = int(row.get("revision") or index)
            if declared_revision != index:
                raise InvalidActionTransition(
                    f"invalid restored transition revision: expected {index}, got {declared_revision}"
                )
            target = ActionPhase(str(row.get("to") or ""))
            machine.transition(
                target,
                cause=str(row.get("cause") or "restored"),
                facts=dict(row.get("facts") or {}),
            )
        machine.transitions = [dict(row) for row in transitions or []]
        machine.revision = len(machine.transitions)
        return machine

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
