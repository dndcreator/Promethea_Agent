from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_module: str = "gateway"
    severity: str = "info"
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None

    @classmethod
    def from_emission(
        cls,
        *,
        event_type: str,
        payload: Dict[str, Any],
        seq: Optional[int] = None,
    ) -> "TraceEvent":
        body = payload or {}
        return cls(
            trace_id=(str(body.get("trace_id")) if body.get("trace_id") else None),
            request_id=(str(body.get("request_id")) if body.get("request_id") else None),
            session_id=(str(body.get("session_id")) if body.get("session_id") else None),
            user_id=(str(body.get("user_id")) if body.get("user_id") else None),
            agent_id=(str(body.get("agent_id")) if body.get("agent_id") else None),
            event_type=event_type,
            source_module=str(body.get("source_module") or "gateway"),
            severity=str(body.get("severity") or "info"),
            payload=dict(body),
            seq=seq,
        )
