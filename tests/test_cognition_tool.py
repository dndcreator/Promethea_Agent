from types import SimpleNamespace

import pytest

from gateway.capability_service import ToolInvocationContext
from gateway.official_tools.cognition_tools import CognitionRecallTool


class _SelfModel:
    def __init__(self):
        self.kwargs = None

    async def recall_cognition(self, **kwargs):
        self.kwargs = kwargs
        return {"ok": True, "snapshot": {"mode": "fast"}}


@pytest.mark.asyncio
async def test_cognition_tool_uses_trusted_invocation_identity():
    service = _SelfModel()
    tool = CognitionRecallTool(self_model_service=service)
    run_context = SimpleNamespace(trace_id="trace-1")
    ctx = ToolInvocationContext(
        user_id="trusted-user",
        session_id="trusted-session",
        source="conversation",
        metadata={"run_context": run_context, "user_config": {}},
    )

    result = await tool.invoke(
        {
            "query": "What changed?",
            "facets": ["before", "after"],
            "mode": "adaptive",
            "user_id": "untrusted-user",
        },
        ctx,
    )

    assert result["ok"] is True
    assert service.kwargs["user_id"] == "trusted-user"
    assert service.kwargs["session_id"] == "trusted-session"
    assert service.kwargs["facets"] == ["before", "after"]
