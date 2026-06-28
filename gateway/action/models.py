from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActionContext:
    """Context for an already-classified action turn."""

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    user_config: Optional[Dict[str, Any]] = None
    run_context: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRun:
    """Runtime state for one action-mode turn."""

    goal: str
    messages: List[Dict[str, Any]]
    context: ActionContext
    budget: Optional[int] = None
    run_id: str = field(default_factory=lambda: f"act_{uuid.uuid4().hex}")
    status: str = "pending"
    trace: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None

    def add_trace(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.trace.append(
            {
                "event": event,
                "at": time.time(),
                "payload": dict(payload or {}),
            }
        )


@dataclass
class ActionResult:
    """Structured result returned from ActionService to ConversationService."""

    status: str
    content: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None

    def to_chat_loop_result(self) -> Dict[str, Any]:
        payload = dict(self.raw or {})
        payload["status"] = self.status
        payload["content"] = self.content
        payload["action_run_id"] = self.run_id
        payload["action_trace"] = list(self.trace or [])
        if self.usage is not None:
            payload["usage"] = self.usage
        return payload
