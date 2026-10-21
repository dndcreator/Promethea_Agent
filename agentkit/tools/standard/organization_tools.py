from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.capability_service import ToolInvocationContext
from gateway.tools.schema import input_object, integer, text


class OrganizationRecallTool:
    input_schema = input_object(
        {
            "query": text(),
            "audience": text(),
            "context_type": text(),
            "top_k": integer(minimum=1, maximum=50),
        },
        required=("query",),
    )
    tool_id = "organization.recall"
    side_effect_level = "read_only"
    name = tool_id
    description = (
        "Recall governed organization knowledge, policy, terminology, templates, and writing style "
        "for the current organization. Use when passive organization context is insufficient."
    )
    domain = "organization"
    requires_config = "org_brain.enabled"
    presentation = {
        "kind": "memory",
        "title": "Recall organization knowledge",
        "title_i18n": {"zh": "检索组织知识", "en": "Recall organization knowledge"},
        "subject_arg": "query",
        "references": [{"kind": "organization", "arg": "query"}],
    }

    def __init__(self, *, org_context_service: Any) -> None:
        self.org_context_service = org_context_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        metadata = dict(ctx.metadata or {}) if ctx else {}
        user_config = metadata.get("user_config") if isinstance(metadata.get("user_config"), dict) else {}
        return await self.org_context_service.recall_for_turn(
            query=query,
            user_id=str((ctx.user_id if ctx else "") or "default_user"),
            user_config=user_config,
            audience=str((args or {}).get("audience") or ""),
            context_type=str((args or {}).get("context_type") or "writing"),
            top_k=int((args or {}).get("top_k") or 8),
        )

    @staticmethod
    def result_summary(result: Any) -> str:
        if not isinstance(result, dict):
            return "Organization recall completed"
        items = list(result.get("items") or [])
        if not items:
            return "No relevant organization knowledge was recalled"
        return f"Recalled {len(items)} governed organization knowledge items"

