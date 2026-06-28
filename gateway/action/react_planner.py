from __future__ import annotations

from typing import Any, Dict, Optional

from agentkit.mcp.action_protocol import build_action_mode_contract

from .models import ActionRun, ActionResult


ACTION_MODE_CONTRACT = build_action_mode_contract()


class ReActPlanner:
    """
    Adapter around the existing lightweight ReAct/tool-call loop.

    The planner owns the "next action from observations" strategy, while
    ActionService owns run state, trace, and service boundaries.
    """

    def __init__(self, conversation_core: Any):
        self.conversation_core = conversation_core

    async def run(
        self,
        action_run: ActionRun,
        *,
        tool_executor: Optional[Any] = None,
    ) -> ActionResult:
        ctx = action_run.context
        messages = list(action_run.messages or [])
        messages.append({"role": "system", "content": ACTION_MODE_CONTRACT})
        response = await self.conversation_core.run_chat_loop(
            messages,
            user_config=ctx.user_config,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            tool_executor=tool_executor,
            max_recursion=action_run.budget,
        )
        raw: Dict[str, Any] = response if isinstance(response, dict) else {"raw": response}
        return ActionResult(
            status=str(raw.get("status") or "success"),
            content=str(raw.get("content") or ""),
            raw=raw,
            run_id=action_run.run_id,
            trace=list(action_run.trace),
            usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else None,
        )
