from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from .session_state import SessionState


class RunContext(BaseModel):
    """Run-level execution context for a single gateway turn."""

    request_id: str
    trace_id: str
    session_state: SessionState
    user_identity: Dict[str, Any] = Field(default_factory=dict)
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    normalized_input: Dict[str, Any] = Field(default_factory=dict)
    memory_bundle: Dict[str, Any] = Field(default_factory=dict)
    tool_availability: Dict[str, Any] = Field(default_factory=dict)
    tool_policy: Dict[str, Any] = Field(default_factory=dict)
    reasoning_state: Dict[str, Any] = Field(default_factory=dict)
    prompt_blocks: Dict[str, Any] = Field(default_factory=dict)
    prompt_block_policy: Dict[str, Any] = Field(default_factory=dict)
    requested_mode: Optional[str] = None
    requested_skill: Optional[str] = None
    active_skill: Dict[str, Any] = Field(default_factory=dict)
    token_budget: Optional[int] = None
    cost_budget: Optional[float] = None
    workspace_handle: Dict[str, Any] = Field(default_factory=dict)
    event_buffer: list[Dict[str, Any]] = Field(default_factory=list)
    debug_flags: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def session_id(self) -> str:
        return self.session_state.session_id

    @property
    def user_id(self) -> str:
        return self.session_state.user_id
