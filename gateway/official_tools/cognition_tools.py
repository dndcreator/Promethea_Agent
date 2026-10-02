from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.capability_service import ToolInvocationContext


class CognitionRecallTool:
    """Expose query-conditioned cognition without moving ownership into Memory."""

    tool_id = "cognition.recall"
    side_effect_level = "read_only"
    name = "cognition.recall"
    description = (
        "Build a query-conditioned cognition snapshot from governed memory and current runtime context. "
        "Use it when an answer requires cross-memory synthesis, changing facts, conflicts, or multi-hop recall."
    )
    official = True
    official_domain = "cognition"

    def __init__(self, *, self_model_service: Any) -> None:
        self.self_model_service = self_model_service

    async def invoke(
        self,
        args: Dict[str, Any],
        ctx: Optional[ToolInvocationContext] = None,
    ) -> Any:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        facets = args.get("facets") if isinstance(args.get("facets"), list) else []
        mode = str((args or {}).get("mode") or "auto").strip().lower()
        if mode not in {"auto", "fast", "adaptive", "deep"}:
            raise ValueError("mode must be auto, fast, adaptive, or deep")
        deadline_value = (args or {}).get("deadline_ms")
        deadline_ms = int(deadline_value) if deadline_value is not None else None
        metadata = dict(ctx.metadata or {}) if ctx else {}
        return await self.self_model_service.recall_cognition(
            user_id=str((ctx.user_id if ctx else "") or "default_user"),
            session_id=str((ctx.session_id if ctx else "") or "default"),
            query=query,
            run_context=metadata.get("run_context"),
            facets=[str(value) for value in facets if str(value).strip()],
            mode=mode,
            deadline_ms=deadline_ms,
            user_config=metadata.get("user_config") if isinstance(metadata.get("user_config"), dict) else None,
        )
