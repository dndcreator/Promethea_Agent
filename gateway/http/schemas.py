from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from gateway.public_contracts import RunRequest, RunResponse


class ChatRequest(RunRequest):
    """HTTP binding of the transport-neutral run request."""


class ChatResponse(RunResponse):
    """HTTP binding of the transport-neutral run response."""


class FollowUpRequest(BaseModel):
    selected_text: str
    query_type: str  # why/risk/alternative/custom
    custom_query: Optional[str] = None
    session_id: str
    message_id: str
    start_offset: int = 0
    end_offset: int = 0


class UserLogin(BaseModel):
    username: str
    password: str
    remember_me: Optional[bool] = True


class UserRegister(BaseModel):
    username: str
    password: str
    agent_name: Optional[str] = "Promethea"


class ChannelBindRequest(BaseModel):
    channel: str
    account_id: str


class UserDeleteRequest(BaseModel):
    confirm: bool = False


class ConfirmToolRequest(BaseModel):
    session_id: str
    tool_call_id: str
    action: str # "approve" or "reject"


class BatchRequestItem(BaseModel):
    method: str
    params: Dict = Field(default_factory=dict)
    timeout_ms: Optional[int] = None
    retries: int = 0
    priority: int = 0


class BatchRequest(BaseModel):
    requests: List[BatchRequestItem]
