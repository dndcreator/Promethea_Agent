from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from gateway.events import EventEmitter


class SecurityAuditService:
    """Builds user-scoped security audit summaries from event bus audit history."""

    def __init__(self, event_emitter: EventEmitter) -> None:
        self.event_emitter = event_emitter

    def build_report(
        self,
        *,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        bounded_limit = max(1, min(int(limit or 100), 500))

        violations = self._to_rows(
            self.event_emitter.get_audit_history(
                user_id=user_id,
                action="namespace_violation_attempt",
                limit=bounded_limit,
            )
        )
        side_effects = self._to_rows(
            self.event_emitter.get_audit_history(
                user_id=user_id,
                action="side_effect_tool_execution",
                limit=bounded_limit,
            )
        )
        workspace_blocks = self._to_rows(
            self.event_emitter.get_audit_history(
                user_id=user_id,
                action="workspace_write_blocked",
                limit=bounded_limit,
            )
        )
        secret_access = self._to_rows(
            self.event_emitter.get_audit_history(
                user_id=user_id,
                action="secret_access",
                limit=bounded_limit,
            )
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "user_id": user_id,
            "limit": bounded_limit,
            "summary": {
                "namespace_violations": len(violations),
                "side_effect_tool_events": len(side_effects),
                "workspace_blocked_events": len(workspace_blocks),
                "secret_access_events": len(secret_access),
            },
            "violations": violations,
            "side_effect_tools": side_effects,
            "workspace_blocks": workspace_blocks,
            "secret_access": secret_access,
        }

    @staticmethod
    def _to_rows(events: list[Any]) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        for event in events:
            if hasattr(event, "model_dump"):
                rows.append(event.model_dump())
            elif isinstance(event, dict):
                rows.append(dict(event))
        return rows
