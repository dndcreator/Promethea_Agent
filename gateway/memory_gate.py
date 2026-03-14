from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


MemoryLayer = Literal[
    "working_memory",
    "episodic_memory",
    "semantic_memory",
    "profile_memory",
    "reasoning_template_memory",
]
MemoryDecisionStatus = Literal["allow", "deny", "defer"]


class MemoryWriteRequest(BaseModel):
    source_text: str = ""
    source_turn: Dict[str, Any] = Field(default_factory=dict)
    proposed_memory_type: str = ""
    extracted_content: str = ""
    confidence: float = 0.0
    related_entities: List[str] = Field(default_factory=list)
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    conflict_candidates: List[str] = Field(default_factory=list)


class MemoryWriteDecision(BaseModel):
    decision: MemoryDecisionStatus
    target_memory_layer: MemoryLayer
    reason: str
    reasons: List[str] = Field(default_factory=list)
    conflict_candidates: List[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryWriteGate:
    _SPECULATIVE_RE = re.compile(
        r"\b(maybe|might|perhaps|guess|probably|assume|uncertain|rumor|估计|可能|也许|大概|猜测)\b",
        re.IGNORECASE,
    )
    _SHORT_LIVED_RE = re.compile(
        r"\b(today|tonight|tomorrow|this week|for now|temporary|temp|临时|暂时|今天|明天|本周)\b",
        re.IGNORECASE,
    )

    _PROFILE_TYPES = {"preference", "constraint", "identity"}
    _EPISODIC_TYPES = {"goal", "project_state"}

    def evaluate(self, request: MemoryWriteRequest) -> MemoryWriteDecision:
        reasons: List[str] = []
        content = (request.extracted_content or "").strip()
        source_text = (request.source_text or "").strip()
        proposed_type = (request.proposed_memory_type or "").strip().lower()
        confidence = float(request.confidence or 0.0)
        conflicts = [str(item).strip() for item in request.conflict_candidates if str(item).strip()]

        layer = self._resolve_layer(proposed_type)

        if confidence < 0.45:
            reasons.append("low_confidence")
            return MemoryWriteDecision(
                decision="deny",
                target_memory_layer=layer,
                reason="low_confidence",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence},
            )

        if self._looks_speculative(content) or self._looks_speculative(source_text):
            reasons.append("speculative_content")
            return MemoryWriteDecision(
                decision="deny",
                target_memory_layer=layer,
                reason="speculative_content",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence},
            )

        if self._looks_short_lived(content) or self._looks_short_lived(source_text):
            reasons.append("short_lived_context")
            return MemoryWriteDecision(
                decision="defer",
                target_memory_layer="working_memory",
                reason="short_lived_context",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence},
            )

        if conflicts:
            reasons.append("conflict_detected")
            return MemoryWriteDecision(
                decision="defer",
                target_memory_layer=layer,
                reason="conflict_detected",
                reasons=reasons,
                conflict_candidates=conflicts,
                requires_user_confirmation=True,
                metadata={"confidence": confidence},
            )

        reasons.append("durable_factual_state")
        return MemoryWriteDecision(
            decision="allow",
            target_memory_layer=layer,
            reason="durable_factual_state",
            reasons=reasons,
            conflict_candidates=conflicts,
            metadata={"confidence": confidence},
        )

    def _resolve_layer(self, proposed_type: str) -> MemoryLayer:
        if proposed_type in self._PROFILE_TYPES:
            return "profile_memory"
        if proposed_type in self._EPISODIC_TYPES:
            return "episodic_memory"
        return "semantic_memory"

    def _looks_speculative(self, text: str) -> bool:
        return bool(text and self._SPECULATIVE_RE.search(text))

    def _looks_short_lived(self, text: str) -> bool:
        return bool(text and self._SHORT_LIVED_RE.search(text))
