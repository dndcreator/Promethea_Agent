from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryRecallRequest(BaseModel):
    request_id: str
    trace_id: str
    session_id: str
    user_id: str
    query_text: str
    normalized_query: str = ""
    mode: str = "fast"
    agent_id: Optional[str] = None
    workspace_id: Optional[str] = None
    active_skill_id: Optional[str] = None
    active_workflow_id: Optional[str] = None
    top_k: int = 5
    allowed_memory_types: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    debug_flags: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecalledMemoryItem(BaseModel):
    memory_id: str
    memory_type: str = ""
    source_layer: str = ""
    content: str = ""
    relevance_score: float = 0.0
    confidence: float = 0.0
    recall_reason: str = ""
    source_session: Optional[str] = None
    source_turn: Optional[str] = None
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    staleness_flag: bool = False
    conflict_flag: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DroppedRecallCandidate(BaseModel):
    memory_id: str
    source_layer: str = ""
    content: str = ""
    reason: str = ""
    detail: str = ""
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryRecallResult(BaseModel):
    request_id: str
    trace_id: str
    session_id: str
    user_id: str
    memory_records: List[RecalledMemoryItem] = Field(default_factory=list)
    summary: str = ""
    formatted_context: str = ""
    recall_strategy: Dict[str, Any] = Field(default_factory=dict)
    applied_filters: List[str] = Field(default_factory=list)
    dropped_candidates: List[DroppedRecallCandidate] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
