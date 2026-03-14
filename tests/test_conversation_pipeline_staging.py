from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.conversation_pipeline import (
    run_staged_pipeline,
    stage_input_normalization,
    stage_mode_detection,
)
from gateway.conversation_service import ConversationService
from gateway.protocol import (
    ConversationRunInput,
    EventType,
    MemoryRecallBundle,
    ModeDecision,
    NormalizedInput,
    PlanResult,
    ResponseDraft,
    ToolExecutionBundle,
)


class _DummyCore:
    async def run_chat_loop(self, messages, user_config=None, session_id=None, user_id=None, tool_executor=None):
        return {"status": "success", "content": "ok"}

    async def call_llm(self, messages, user_config=None, user_id=None):
        return {"content": "{\"recall\": false}"}


@pytest.mark.asyncio
async def test_pipeline_stage_order(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    order = []

    async def _n(svc, run_input):
        order.append("input_normalization")
        return NormalizedInput(user_message="hello", session_id="s1", user_id="u1", channel="web")

    async def _m(svc, normalized):
        order.append("mode_detection")
        return ModeDecision(mode="fast", reason="test")

    async def _mr(svc, **kwargs):
        order.append("memory_recall")
        return MemoryRecallBundle(recalled=False)

    async def _pr(svc, **kwargs):
        order.append("planning_reasoning")
        return PlanResult(used_reasoning=False, base_system_prompt="sys")

    async def _te(svc, **kwargs):
        order.append("tool_execution")
        return ToolExecutionBundle(enabled=False)

    async def _rs(svc, **kwargs):
        order.append("response_synthesis")
        return ResponseDraft(status="success", content="ok", messages=[], response_data={"status": "success", "content": "ok"})

    monkeypatch.setattr("gateway.conversation_pipeline.stage_input_normalization", _n)
    monkeypatch.setattr("gateway.conversation_pipeline.stage_mode_detection", _m)
    monkeypatch.setattr("gateway.conversation_pipeline.stage_memory_recall", _mr)
    monkeypatch.setattr("gateway.conversation_pipeline.stage_plan_or_reason", _pr)
    monkeypatch.setattr("gateway.conversation_pipeline.stage_tool_execution", _te)
    monkeypatch.setattr("gateway.conversation_pipeline.stage_response_synthesis", _rs)

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    assert order == [
        "input_normalization",
        "mode_detection",
        "memory_recall",
        "planning_reasoning",
        "tool_execution",
        "response_synthesis",
    ]


@pytest.mark.asyncio
async def test_stage_io_models():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    run_input = ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")

    normalized = await stage_input_normalization(service, run_input)
    mode = await stage_mode_detection(service, normalized)

    assert isinstance(normalized, NormalizedInput)
    assert isinstance(mode, ModeDecision)
    assert normalized.user_message == "hello"


@pytest.mark.asyncio
async def test_fast_mode_minimal_path_skips_reasoning(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    reasoning = MagicMock()
    reasoning.is_enabled.return_value = True
    reasoning.run = AsyncMock(side_effect=AssertionError("reasoning should not run in fast mode"))
    service.reasoning_service = reasoning

    out = await service.run_conversation(
        ConversationRunInput(user_message="hi", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    assert out.raw.get("mode") == "fast"
    assert out.raw.get("used_reasoning") is False


@pytest.mark.asyncio
async def test_memory_and_tool_path(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    service._should_recall_memory = AsyncMock(return_value=True)
    memory = MagicMock()
    memory.is_enabled.return_value = True
    memory.get_context = AsyncMock(return_value="memory ctx")
    service.memory_service = memory

    tool_executor = AsyncMock(return_value={"ok": True})

    out = await service.run_conversation(
        ConversationRunInput(
            user_message="please use my memory and call tools",
            session_id="s1",
            user_id="u1",
            tool_executor=tool_executor,
        )
    )

    assert out.status == "success"
    assert out.raw.get("memory_recalled") is True


@pytest.mark.asyncio
async def test_stage_failure_propagation(monkeypatch):
    event_emitter = MagicMock()
    event_emitter.on = MagicMock()
    event_emitter.emit = AsyncMock()
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=event_emitter)

    async def _boom(*args, **kwargs):
        raise RuntimeError("mode failed")

    monkeypatch.setattr("gateway.conversation_pipeline.stage_mode_detection", _boom)

    with pytest.raises(RuntimeError):
        await run_staged_pipeline(
            service,
            ConversationRunInput(user_message="hello", session_id="s1", user_id="u1"),
        )

    emitted = [call.args[0] for call in event_emitter.emit.await_args_list]
    assert EventType.CONVERSATION_STAGE_FAILED in emitted

@pytest.mark.asyncio
async def test_pipeline_exposes_prompt_assembly_debug():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello world", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    prompt_debug = out.raw.get("prompt_assembly")
    assert isinstance(prompt_debug, dict)
    assert "used_block_ids" in prompt_debug


@pytest.mark.asyncio
async def test_fast_mode_prompt_blocks_do_not_include_reasoning():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="quick hello", session_id="s1", user_id="u1")
    )

    prompt_debug = out.raw.get("prompt_assembly") or {}
    used_block_ids = prompt_debug.get("used_block_ids") or []
    assert "reasoning" not in used_block_ids
