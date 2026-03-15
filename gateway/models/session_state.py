from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionState(BaseModel):
    """Session-level runtime state shared across turns."""

    session_id: str
    user_id: str
    agent_id: Optional[str] = None
    channel_id: Optional[str] = None
    workspace_id: Optional[str] = None
    memory_scope: Optional[str] = None
    tool_policy_profile: Optional[str] = None
    reasoning_mode: Optional[str] = None
    active_skill_id: Optional[str] = None
    trace_id: str
    status: str = "active"
    session_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
