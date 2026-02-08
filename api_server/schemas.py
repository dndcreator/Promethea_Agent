from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, List, Dict


class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
    status: str = "success"
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    args: Optional[Dict] = None


class FollowUpRequest(BaseModel):
    # 用户手动选中的文本
    selected_text: str
    query_type: str  # why/risk/alternative/custom
    custom_query: Optional[str] = None  # 自定义追问
    session_id: str
    context: Optional[List[Dict]] = None  # 最近几轮对话上下文


class UserLogin(BaseModel):
    username: str
    password: str


class UserRegister(BaseModel):
    username: str
    password: str
    agent_name: Optional[str] = "Promethea"


class APIConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class UserConfigUpdate(BaseModel):
    agent_name: Optional[str] = None
    system_prompt: Optional[str] = None
    api: Optional[APIConfigUpdate] = None


class ChannelBindRequest(BaseModel):
    channel: str
    account_id: str

class ConfirmToolRequest(BaseModel):
    session_id: str
    tool_call_id: str
    action: str # "approve" or "reject"