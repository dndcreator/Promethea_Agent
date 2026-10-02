from types import SimpleNamespace

import pytest

from gateway.official_tools.reasoning_tools import ReasoningRunTool
from gateway.capability_service import ToolInvocationContext


class _ConversationService:
    async def _get_user_prompt_and_config(self, user_id, channel):
        return "core identity", {"user_id": user_id, "channel": channel}


class _ReasoningService:
    def __init__(self):
        self.received = None

    async def run(self, **kwargs):
        self.received = kwargs
        return {"used_reasoning": True, "reasoning_summary": "done", "tree_id": "tree-1"}


class _MessageManager:
    def get_recent_messages(self, session_id, user_id=None):
        return [{"role": "user", "content": f"history:{session_id}:{user_id}"}]


@pytest.mark.asyncio
async def test_reasoning_tool_delegates_to_existing_service_without_reclassification():
    reasoning = _ReasoningService()
    gateway = SimpleNamespace(
        reasoning_service=reasoning,
        conversation_service=_ConversationService(),
        message_manager=_MessageManager(),
    )
    run_context = SimpleNamespace(trace_id="trace-1")
    tool = ReasoningRunTool(gateway_server=gateway)

    result = await tool.invoke(
        {"objective": "analyze the architecture"},
        ToolInvocationContext(
            session_id="session-1",
            user_id="user-1",
            metadata={"run_context": run_context, "user_config": {"custom": True}},
        ),
    )

    assert result["used_reasoning"] is True
    assert reasoning.received["force_reasoning"] is True
    assert reasoning.received["run_context"] is run_context
    assert reasoning.received["user_config"] == {"custom": True}
    assert reasoning.received["recent_messages"][0]["content"].startswith("history:")
