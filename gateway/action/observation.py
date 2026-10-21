from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agentkit.mcp.tool_result import ToolExecutionResult


@dataclass(frozen=True)
class RuntimeObservation:
    action_loop_id: str
    model_step_id: str
    tool_call_id: str
    tool_name: str
    ok: bool
    structured_result: Any = None
    model_projection: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    scope: Dict[str, Any] = field(default_factory=dict)
    capability_snapshot_id: Optional[str] = None
    observation_id: str = field(default_factory=lambda: f"obs_{uuid.uuid4().hex}")
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    @classmethod
    def from_result(
        cls,
        *,
        action_loop_id: str,
        model_step_id: str,
        tool_call_id: str,
        tool_name: str,
        result: ToolExecutionResult,
        capability_snapshot_id: Optional[str],
        scope: Optional[Dict[str, Any]] = None,
    ) -> "RuntimeObservation":
        return cls(
            action_loop_id=action_loop_id,
            model_step_id=model_step_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            ok=bool(result.ok),
            structured_result=result.value,
            model_projection=[dict(item) for item in result.content],
            error=result.error.as_dict() if result.error else None,
            scope={str(key): value for key, value in dict(scope or {}).items() if value not in (None, "")},
            capability_snapshot_id=capability_snapshot_id,
        )

    def model_content(self) -> List[Dict[str, Any]]:
        """Project one committed Runtime fact into provider-neutral content blocks."""
        text_result = "\n".join(
            str(item.get("text") or "")
            for item in self.model_projection
            if isinstance(item, dict) and str(item.get("type") or "") == "text"
        ).strip()
        fact = {
            "observation_id": self.observation_id,
            "subject": self.tool_name,
            "status": "completed" if self.ok else "failed",
            "scope": self.scope,
            "result": (self.structured_result if self.structured_result is not None else text_result) if self.ok else None,
            "error": self.error,
        }
        blocks: List[Dict[str, Any]] = [{
            "type": "text",
            "text": json.dumps(fact, ensure_ascii=False, sort_keys=True, default=str),
        }]
        blocks.extend(
            dict(item)
            for item in self.model_projection
            if isinstance(item, dict) and str(item.get("type") or "") != "text"
        )
        return blocks

    def as_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "action_loop_id": self.action_loop_id,
            "model_step_id": self.model_step_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "status": "completed" if self.ok else "failed",
            "structured_result": self.structured_result,
            "model_projection": list(self.model_projection),
            "error": self.error,
            "scope": dict(self.scope),
            "capability_snapshot_id": self.capability_snapshot_id,
            "occurred_at": self.occurred_at,
        }
