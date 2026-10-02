from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.capability_service import ToolInvocationContext


class ReasoningRunTool:
    """Expose the existing ReasoningService to the main-model control loop."""

    tool_id = "reasoning.run"
    side_effect_level = "workspace_write"
    name = "reasoning.run"
    description = (
        "Run Promethea's deeper reasoning service for a complex objective when a direct "
        "answer or a lightweight tool call is insufficient."
    )
    official = True
    official_domain = "reasoning"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(
        self,
        args: Dict[str, Any],
        ctx: Optional[ToolInvocationContext] = None,
    ) -> Any:
        objective = str((args or {}).get("objective") or "").strip()
        if not objective:
            raise ValueError("objective is required")

        service = getattr(self.gateway_server, "reasoning_service", None)
        if service is None:
            raise RuntimeError("reasoning service is unavailable")

        user_id = str((ctx.user_id if ctx else "") or "default_user")
        session_id = str((ctx.session_id if ctx else "") or "default_session")
        metadata = dict(ctx.metadata or {}) if ctx else {}
        user_config = metadata.get("user_config")
        run_context = metadata.get("run_context")

        conversation_service = getattr(self.gateway_server, "conversation_service", None)
        base_system_prompt = ""
        if conversation_service is not None:
            base_system_prompt, resolved_config = await conversation_service._get_user_prompt_and_config(
                user_id,
                "web",
            )
            if user_config is None:
                user_config = resolved_config

        recent_messages = []
        message_manager = getattr(self.gateway_server, "message_manager", None)
        if message_manager is not None:
            recent_messages = message_manager.get_recent_messages(session_id, user_id=user_id)

        return await service.run(
            session_id=session_id,
            user_id=user_id,
            user_message=objective,
            recent_messages=recent_messages,
            base_system_prompt=base_system_prompt,
            user_config=user_config,
            run_context=run_context,
            force_reasoning=True,
        )
