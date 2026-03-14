from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.memory_service import MemoryService
from gateway.models import RunContext, SessionState
from gateway.protocol import EventType
from gateway.reasoning_service import ReasoningService
from gateway.tool_service import ToolInvocationContext, ToolService


class _DummyConversationCore:
    async def call_llm(self, messages, user_config=None, user_id=None):
        return {"content": "{}"}


def _build_run_context() -> RunContext:
    state = SessionState(session_id="s1", user_id="u1", trace_id="t1")
    return RunContext(request_id="r1", trace_id="t1", session_state=state)


@pytest.mark.asyncio
async def test_memory_recall_event_includes_run_context_fields():
    event_emitter = MagicMock()
    event_emitter.on = MagicMock()
    event_emitter.emit = AsyncMock()

    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.get_context.return_value = "ctx"

    service = MemoryService(event_emitter=event_emitter, memory_adapter=memory_adapter)
    run_context = _build_run_context()

    text = await service.get_context(
        query="hello",
        session_id="s1",
        user_id="u1",
        run_context=run_context,
    )

    assert text == "ctx"
    event_name, payload = event_emitter.emit.await_args.args
    assert event_name == EventType.MEMORY_RECALLED
    assert payload["trace_id"] == "t1"
    assert payload["request_id"] == "r1"
    assert payload["session_id"] == "s1"
    assert payload["user_id"] == "u1"


@pytest.mark.asyncio
async def test_tool_events_include_run_context_fields():
    event_emitter = MagicMock()
    event_emitter.emit = AsyncMock()

    service = ToolService(event_emitter=event_emitter, mcp_manager=MagicMock())

    class _LocalTool:
        tool_id = "local.echo"
        name = "Echo"
        description = "echo"

        async def invoke(self, args, ctx=None):
            return {"ok": True, "args": args}

    service.register_tool(_LocalTool())
    run_context = _build_run_context()

    await service.call_tool(
        "local.echo",
        {"x": 1},
        ctx=ToolInvocationContext(session_id="s1", user_id="u1", source="chat"),
        request_id="r1",
        run_context=run_context,
    )

    event_name, payload = event_emitter.emit.await_args_list[0].args
    assert event_name == EventType.TOOL_CALL_START
    assert payload["trace_id"] == "t1"
    assert payload["request_id"] == "r1"
    assert payload["session_id"] == "s1"
    assert payload["user_id"] == "u1"


@pytest.mark.asyncio
async def test_reasoning_start_event_includes_run_context_fields(monkeypatch):
    service = ReasoningService(
        event_emitter=None,
        conversation_core=_DummyConversationCore(),
    )

    emitted = []

    async def _capture(event, payload):
        emitted.append((event, payload))

    async def _gate(**kwargs):
        return {
            "needs_reasoning": True,
            "needs_memory": False,
            "needs_tools": False,
            "complexity": "high",
            "reason": "test",
        }

    async def _plan(**kwargs):
        return [{"title": "t", "goal": "g", "requires_memory": False, "requires_tools": False}]

    async def _execute(**kwargs):
        return []

    async def _summ(**kwargs):
        return ""

    monkeypatch.setattr(service, "_emit", _capture)
    monkeypatch.setattr(service, "_gate_reasoning", _gate)
    monkeypatch.setattr(service, "_plan_steps", _plan)
    monkeypatch.setattr(service, "_execute_step", _execute)
    monkeypatch.setattr(service, "_summarize_tree", _summ)

    run_context = _build_run_context()
    result = await service.run(
        session_id="s1",
        user_id="u1",
        user_message="complex",
        recent_messages=[],
        base_system_prompt="sys",
        user_config={"reasoning": {"enabled": True}},
        run_context=run_context,
    )

    assert result["used_reasoning"] is True
    start_payloads = [p for e, p in emitted if e == EventType.REASONING_START]
    assert start_payloads
    assert start_payloads[0]["trace_id"] == "t1"
    assert start_payloads[0]["request_id"] == "r1"
    assert start_payloads[0]["session_id"] == "s1"
    assert start_payloads[0]["user_id"] == "u1"
