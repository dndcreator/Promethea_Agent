from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from .trace import TraceEvent


class AuditEvent(BaseModel):
    audit_id: str = Field(default_factory=lambda: f"audit_{datetime.now(timezone.utc).timestamp()}")
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    event_type: str
    action: str
    outcome: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_module: str = "gateway"
    severity: str = "info"
    details: Dict[str, Any] = Field(default_factory=dict)


_SIDE_EFFECT_LEVELS = {"workspace_write", "external_write", "privileged_host_action"}


def infer_audit_event(trace_event: TraceEvent) -> Optional[AuditEvent]:
    et = trace_event.event_type
    payload = trace_event.payload or {}

    if et in {"tool.call.start", "tool.execution.started", "tool.call.error", "tool.execution.failed"}:
        spec = payload.get("tool_spec") if isinstance(payload.get("tool_spec"), dict) else {}
        raw_side_effect = spec.get("side_effect_level")
        side_effect = getattr(raw_side_effect, "value", raw_side_effect)
        side_effect = str(side_effect or "").lower()
        if "." in side_effect:
            side_effect = side_effect.split(".")[-1]
        if side_effect in _SIDE_EFFECT_LEVELS:
            if et in {"tool.call.error", "tool.execution.failed"}:
                outcome = "failed"
                reason = str(payload.get("error") or "tool execution failed")
            else:
                outcome = "attempted"
                reason = "side-effect tool execution started"
            return AuditEvent(
                trace_id=trace_event.trace_id,
                request_id=trace_event.request_id,
                session_id=trace_event.session_id,
                user_id=trace_event.user_id,
                event_type=et,
                action="side_effect_tool_execution",
                outcome=outcome,
                source_module=trace_event.source_module,
                severity="warning",
                details={
                    "tool_name": spec.get("full_name") or payload.get("tool_name") or payload.get("tool_id"),
                    "side_effect_level": side_effect,
                    "reason": reason,
                },
            )

    if et == "workspace.artifact.written":
        return AuditEvent(
            trace_id=trace_event.trace_id,
            request_id=trace_event.request_id,
            session_id=trace_event.session_id,
            user_id=trace_event.user_id,
            event_type=et,
            action="workspace_artifact_write",
            outcome=str(payload.get("operation") or "written"),
            source_module=trace_event.source_module,
            severity="info",
            details=dict(payload),
        )

    if et == "workspace.write.blocked":
        return AuditEvent(
            trace_id=trace_event.trace_id,
            request_id=trace_event.request_id,
            session_id=trace_event.session_id,
            user_id=trace_event.user_id,
            event_type=et,
            action="workspace_write_blocked",
            outcome="blocked",
            source_module=trace_event.source_module,
            severity="warning",
            details=dict(payload),
        )
    if et == "memory.write.decided":
        return AuditEvent(
            trace_id=trace_event.trace_id,
            request_id=trace_event.request_id,
            session_id=trace_event.session_id,
            user_id=trace_event.user_id,
            event_type=et,
            action="memory_write_decision",
            outcome=str(payload.get("decision") or payload.get("status") or "recorded"),
            source_module=trace_event.source_module,
            severity="info",
            details=dict(payload),
        )

    if et == "security.boundary.violation":
        return AuditEvent(
            trace_id=trace_event.trace_id,
            request_id=trace_event.request_id,
            session_id=trace_event.session_id,
            user_id=trace_event.user_id,
            event_type=et,
            action="namespace_violation_attempt",
            outcome=str(payload.get("outcome") or "blocked"),
            source_module=trace_event.source_module,
            severity="warning",
            details=dict(payload),
        )

    if et == "security.secret.access":
        return AuditEvent(
            trace_id=trace_event.trace_id,
            request_id=trace_event.request_id,
            session_id=trace_event.session_id,
            user_id=trace_event.user_id,
            event_type=et,
            action="secret_access",
            outcome=str(payload.get("outcome") or "attempted"),
            source_module=trace_event.source_module,
            severity="warning",
            details=dict(payload),
        )
    if et in {"request.failed", "tool.call.error"}:
        msg = str(payload.get("error") or "").lower()
        if any(k in msg for k in ("permission", "policy", "deny", "blocked")):
            return AuditEvent(
                trace_id=trace_event.trace_id,
                request_id=trace_event.request_id,
                session_id=trace_event.session_id,
                user_id=trace_event.user_id,
                event_type=et,
                action="policy_violation_attempt",
                outcome="blocked",
                source_module=trace_event.source_module,
                severity="warning",
                details={"error": payload.get("error")},
            )

    return None


