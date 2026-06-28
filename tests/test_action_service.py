from __future__ import annotations

import pytest

from gateway.action import ActionService
from gateway.conversation_service import ConversationService


class _Core:
    def __init__(self):
        self.calls = []

    async def run_chat_loop(
        self,
        messages,
        user_config=None,
        session_id=None,
        user_id=None,
        tool_executor=None,
        max_recursion=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "user_config": user_config,
                "session_id": session_id,
                "user_id": user_id,
                "tool_executor": tool_executor,
                "max_recursion": max_recursion,
            }
        )
        return {
            "status": "success",
            "content": "action complete",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }


@pytest.mark.asyncio
async def test_action_service_wraps_react_planner_with_trace():
    core = _Core()
    service = ActionService(conversation_core=core)

    out = await service.run_light_action(
        goal="lookup news",
        messages=[{"role": "user", "content": "lookup news"}],
        session_id="s1",
        user_id="u1",
        budget=3,
    )

    assert out["status"] == "success"
    assert out["content"] == "action complete"
    assert out["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert out["action_run_id"].startswith("act_")
    assert [x["event"] for x in out["action_trace"]] == [
        "action.started",
        "action.finished",
    ]
    assert core.calls[0]["max_recursion"] == 3
    assert core.calls[0]["session_id"] == "s1"
    assert core.calls[0]["messages"][-1]["role"] == "system"
    assert "Action mode contract" in core.calls[0]["messages"][-1]["content"]
    assert "strict JSON action object" in core.calls[0]["messages"][-1]["content"]
    assert '"action":"tool_call"' in core.calls[0]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_conversation_service_delegates_chat_loop_to_action_service():
    core = _Core()
    action = ActionService(conversation_core=core)
    conversation = ConversationService(conversation_core=core, action_service=action)

    out = await conversation.run_chat_loop(
        [{"role": "user", "content": "find current data"}],
        session_id="s1",
        user_id="u1",
        max_recursion=3,
    )

    assert out["content"] == "action complete"
    assert out["action_trace"][0]["payload"]["goal"] == "find current data"
    assert core.calls[0]["max_recursion"] == 3
