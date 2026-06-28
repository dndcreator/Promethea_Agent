from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from gateway.events import EventEmitter
from gateway.protocol import EventType

from .models import ActionContext, ActionResult, ActionRun
from .react_planner import ReActPlanner


class ActionService:
    """
    Gateway first-class service for action-mode execution.

    It does not decide whether a user turn needs action, and it does not own
    memory writes. ConversationService/PromptPolicyRouter decide when to enter
    action mode; ActionService manages that action run's state, trace, service
    delegation, and structured result.
    """

    def __init__(
        self,
        *,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Any,
        planner: Optional[ReActPlanner] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core
        self.planner = planner or ReActPlanner(conversation_core)

    async def run_light_action(
        self,
        *,
        goal: str,
        messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        tool_executor: Optional[Any] = None,
        budget: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        action_run = ActionRun(
            goal=str(goal or ""),
            messages=list(messages or []),
            context=ActionContext(
                session_id=session_id,
                user_id=user_id,
                user_config=user_config,
                run_context=run_context,
                metadata=dict(metadata or {}),
            ),
            budget=budget,
        )
        result = await self._run(action_run, tool_executor=tool_executor)
        return result.to_chat_loop_result()

    async def _run(
        self,
        action_run: ActionRun,
        *,
        tool_executor: Optional[Any] = None,
    ) -> ActionResult:
        action_run.status = "running"
        action_run.add_trace(
            "action.started",
            {"goal": action_run.goal, "budget": action_run.budget},
        )
        await self._emit(
            "action.started",
            {
                "action_run_id": action_run.run_id,
                "session_id": action_run.context.session_id,
                "user_id": action_run.context.user_id,
                "goal": action_run.goal,
                "budget": action_run.budget,
            },
        )
        started = time.perf_counter()
        try:
            result = await self.planner.run(action_run, tool_executor=tool_executor)
            action_run.status = result.status or "success"
            action_run.ended_at = time.time()
            action_run.add_trace(
                "action.finished",
                {
                    "status": action_run.status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            result.status = action_run.status
            result.trace = list(action_run.trace)
            await self._emit(
                "action.finished",
                {
                    "action_run_id": action_run.run_id,
                    "session_id": action_run.context.session_id,
                    "user_id": action_run.context.user_id,
                    "status": action_run.status,
                },
            )
            return result
        except Exception as exc:
            logger.exception("ActionService run failed: {}", exc)
            action_run.status = "error"
            action_run.ended_at = time.time()
            action_run.add_trace(
                "action.failed",
                {
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            await self._emit(
                "action.failed",
                {
                    "action_run_id": action_run.run_id,
                    "session_id": action_run.context.session_id,
                    "user_id": action_run.context.user_id,
                    "error": str(exc),
                },
            )
            return ActionResult(
                status="error",
                content=f"Action failed: {exc}",
                raw={"status": "error", "content": f"Action failed: {exc}"},
                run_id=action_run.run_id,
                trace=list(action_run.trace),
            )

    async def _emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        event_type = {
            "action.started": EventType.GATEWAY_RUN_STARTED,
            "action.finished": EventType.RESPONSE_SYNTHESIZED,
            "action.failed": EventType.REQUEST_FAILED,
        }.get(event_name)
        if event_type is None:
            return
        try:
            await self.event_emitter.emit(event_type, {"action": event_name, **payload})
        except Exception as exc:
            logger.debug("ActionService event emit skipped: {}", exc)
