from __future__ import annotations

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
MemoryModality = Literal["actual", "plan", "hypothetical", "unknown"]
MemoryPersistence = Literal["ephemeral", "bounded", "durable", "unknown"]


class MemoryWriteRequest(BaseModel):
    source_text: str = ""
    source_turn: Dict[str, Any] = Field(default_factory=dict)
    proposed_memory_type: str = ""
    extracted_content: str = ""
    confidence: float = 0.0
    modality: MemoryModality = "unknown"
    persistence: MemoryPersistence = "unknown"
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
    _PROFILE_TYPES = {"preference", "constraint", "identity"}
    _EPISODIC_TYPES = {"goal", "project_state"}

    def relationship_requires_confirmation(self, proposed_type: str, relationship: str) -> bool:
        relation = str(relationship or "unclear").strip().lower()
        if relation == "contradicts":
            return True
        return self._resolve_layer(str(proposed_type or "").strip().lower()) == "profile_memory" and relation in {
            "updates",
            "unclear",
        }

    def evaluate(self, request: MemoryWriteRequest) -> MemoryWriteDecision:
        reasons: List[str] = []
        content = (request.extracted_content or "").strip()
        proposed_type = (request.proposed_memory_type or "").strip().lower()
        confidence = float(request.confidence or 0.0)
        modality = str(request.modality or "unknown").strip().lower()
        persistence = str(request.persistence or "unknown").strip().lower()
        conflicts = [str(item).strip() for item in request.conflict_candidates if str(item).strip()]

        layer = self._resolve_layer(proposed_type, persistence=persistence)

        if confidence < 0.45:
            reasons.append("low_confidence")
            return MemoryWriteDecision(
                decision="deny",
                target_memory_layer=layer,
                reason="low_confidence",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
            )

        if modality == "hypothetical":
            reasons.append("hypothetical_state")
            return MemoryWriteDecision(
                decision="deny",
                target_memory_layer=layer,
                reason="hypothetical_state",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
            )

        if persistence == "ephemeral":
            reasons.append("ephemeral_state")
            return MemoryWriteDecision(
                decision="defer",
                target_memory_layer="working_memory",
                reason="ephemeral_state",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
            )

        if modality == "unknown" or persistence == "unknown":
            reasons.append("semantic_scope_unclear")
            return MemoryWriteDecision(
                decision="defer",
                target_memory_layer="working_memory",
                reason="semantic_scope_unclear",
                reasons=reasons,
                conflict_candidates=conflicts,
                metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
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
                metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
            )

        reasons.append("durable_factual_state")
        return MemoryWriteDecision(
            decision="allow",
            target_memory_layer=layer,
            reason="durable_factual_state",
            reasons=reasons,
            conflict_candidates=conflicts,
            metadata={"confidence": confidence, "modality": modality, "persistence": persistence},
        )

    def _resolve_layer(self, proposed_type: str, *, persistence: str = "durable") -> MemoryLayer:
        if persistence == "ephemeral":
            return "working_memory"
        if persistence == "bounded":
            return "episodic_memory"
        if proposed_type in self._PROFILE_TYPES:
            return "profile_memory"
        if proposed_type in self._EPISODIC_TYPES:
            return "episodic_memory"
        return "semantic_memory"
