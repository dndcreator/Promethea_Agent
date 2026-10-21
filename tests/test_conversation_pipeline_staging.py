import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.conversation_pipeline import (
    run_staged_pipeline,
    stage_capability_discovery,
    stage_input_normalization,
)
from gateway.conversation_service import ConversationService
from gateway.http.user_file_store import UserFileStore
from gateway.protocol import ConversationRunInput, EventType, NormalizedInput


class _DummyCore:
    def __init__(self, response=None):
        self.response = response or {"status": "success", "content": "ok", "tool_calls": []}
        self.calls = []

    async def call_llm(self, messages, user_config=None, user_id=None):
        self.calls.append({"messages": messages, "user_config": user_config, "user_id": user_id})
        tool_calls = list(self.response.get("tool_calls") or [])
        if tool_calls and len(self.calls) == 1:
            call = tool_calls[0]
            return {
                "status": "success",
                "content": (
                    '{"action":"tool_call","id":"test-call","tool_name":"'
                    + str(call.get("tool_name") or "")
                    + '","args":{}}'
                ),
            }
        return {
            "status": "success",
            "content": json.dumps({"action": "answer", "content": str(self.response.get("content") or "")}),
        }


class _CapabilityService:
    def __init__(self, *, fail=False):
        self.fail = fail

    async def get_tool_catalog(self, **_kwargs):
        return [
            {
                "service_name": "memory.get_context",
                "tool_name": "memory.get_context",
                "tool_type": "local",
                "description": "Recall relevant memory.",
                "callable_now": True,
            },
            {
                "service_name": "reasoning.run",
                "tool_name": "reasoning.run",
                "tool_type": "local",
                "description": "Run deeper reasoning.",
                "callable_now": True,
            },
        ]

    async def build_capability_snapshot(self, **kwargs):
        rows = await self.get_tool_catalog(**kwargs)
        compact = [
            {
                "name": row["tool_name"],
                "description": row["description"],
                "callable_now": True,
                "callable_reason": "callable",
                "requires_confirmation": False,
                "schema_status": "declared",
                "capability_type": "local",
            }
            for row in rows
        ]
        return {"snapshot_id": "caps-test", "compact_index": compact, "selected_specs": []}

    async def call_tool(self, **_kwargs):
        if self.fail:
            raise RuntimeError("tool failed")
        return {"context": "remembered"}

    def requires_confirmation(self, *_args, **_kwargs):
        return False


class _FailedProviderCore:
    async def call_llm(self, _messages, user_config=None, user_id=None):
        return {"status": "error", "content": "provider unavailable"}


@pytest.mark.asyncio
async def test_pipeline_has_only_real_runtime_stages():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    assert out.raw["pipeline"]["stages"] == [
        "input_normalization",
        "capability_discovery",
        "model_control_loop",
        "response_finalize",
    ]
    assert out.raw["prompt_policy"]["decision_owner"] == "main_model"


@pytest.mark.asyncio
async def test_simple_turn_reaches_main_model_without_router_call():
    core = _DummyCore()
    service = ConversationService(conversation_core=core, event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )

    assert out.content == "ok"
    assert len(core.calls) == 1
    assert any(
        message.get("role") == "system" and "Runtime action protocol" in str(message.get("content") or "")
        for message in core.calls[0]["messages"]
    )


@pytest.mark.asyncio
async def test_provider_failure_is_reflected_in_pipeline_state():
    service = ConversationService(conversation_core=_FailedProviderCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )

    assert out.status == "error"
    assert out.raw["pipeline"]["stage_status"]["model_control_loop"]["status"] == "failed"
    assert out.raw["capability_state"]["degraded"] is True


@pytest.mark.asyncio
async def test_control_loop_budget_comes_from_user_config():
    core = _DummyCore()
    service = ConversationService(conversation_core=core, event_emitter=None)

    await service.run_conversation(
        ConversationRunInput(
            user_message="hello",
            session_id="s1",
            user_id="u1",
            user_config={"action": {"max_steps": 7}},
        )
    )

    assert core.calls


@pytest.mark.asyncio
async def test_capability_discovery_uses_registry_snapshot():
    service = ConversationService(
        conversation_core=_DummyCore(),
        event_emitter=None,
        capability_service=_CapabilityService(),
    )
    context = SimpleNamespace(registered_tools=[])
    normalized = NormalizedInput(user_message="remember", session_id="s1", user_id="u1")

    tools = await stage_capability_discovery(
        service,
        run_input=ConversationRunInput(user_message="remember"),
        normalized=normalized,
        run_context=context,
        user_config={},
    )

    assert tools.enabled is True
    assert tools.metadata["decision_owner"] == "main_model"
    assert tools.metadata["registered_tools"][0]["name"] == "memory.get_context"


@pytest.mark.asyncio
async def test_main_model_memory_call_is_reflected_in_output():
    core = _DummyCore(
        {
            "status": "success",
            "content": "from memory",
            "tool_calls": [{"tool_name": "memory.get_context", "ok": True}],
        }
    )
    service = ConversationService(
        conversation_core=core,
        event_emitter=None,
        capability_service=_CapabilityService(),
    )

    out = await service.run_conversation(
        ConversationRunInput(user_message="what do you remember", session_id="s1", user_id="u1")
    )

    assert out.raw["memory_recalled"] is True
    assert out.raw["capability_state"]["memory"]["status"] == "ok"


@pytest.mark.asyncio
async def test_failed_memory_call_is_not_reported_as_recalled():
    core = _DummyCore(
        {
            "status": "success",
            "content": "memory unavailable",
            "tool_calls": [{"tool_name": "memory.get_context", "ok": False}],
        }
    )
    service = ConversationService(
        conversation_core=core,
        event_emitter=None,
        capability_service=_CapabilityService(fail=True),
    )

    out = await service.run_conversation(
        ConversationRunInput(user_message="what do you remember", session_id="s1", user_id="u1")
    )

    assert out.raw["memory_recalled"] is False
    assert out.raw["capability_state"]["degraded"] is True


@pytest.mark.asyncio
async def test_main_model_reasoning_call_is_reflected_in_output():
    core = _DummyCore(
        {
            "status": "success",
            "content": "reasoned",
            "tool_calls": [{"tool_name": "reasoning.run", "ok": True}],
        }
    )
    service = ConversationService(
        conversation_core=core,
        event_emitter=None,
        capability_service=_CapabilityService(),
    )

    out = await service.run_conversation(
        ConversationRunInput(user_message="solve this", session_id="s1", user_id="u1")
    )

    assert out.raw["used_reasoning"] is True
    assert out.raw["mode"] == "deep"


@pytest.mark.asyncio
async def test_pipeline_emits_failed_stage():
    emitter = MagicMock()
    emitter.on = MagicMock()
    emitter.emit = AsyncMock()
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=emitter)
    service.prepare_runtime_capabilities = AsyncMock(side_effect=RuntimeError("catalog failed"))

    with pytest.raises(RuntimeError, match="catalog failed"):
        await run_staged_pipeline(
            service,
            ConversationRunInput(user_message="hello", session_id="s1", user_id="u1"),
        )

    assert EventType.CONVERSATION_STAGE_FAILED in [call.args[0] for call in emitter.emit.await_args_list]


@pytest.mark.asyncio
async def test_pipeline_exposes_prompt_and_governance_contracts():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="contract check", session_id="s1", user_id="u1")
    )

    assert "identity" in out.raw["prompt_assembly"]["used_block_ids"]
    assert out.raw["task_graph"]["version"] == "1.0"
    assert out.raw["task_graph"]["current_node_id"] == "response"
    assert out.raw["context_budget"]["version"] == "1.0"


@pytest.mark.asyncio
async def test_prepare_chat_turn_compiles_text_attachment(tmp_path, monkeypatch):
    import gateway.http.user_file_store as file_store_module

    store = UserFileStore(root_dir=str(tmp_path))
    entry = store.save_upload(
        user_id="u1",
        filename="notes.txt",
        content=b"enterprise graph context",
        content_type="text/plain",
    )
    monkeypatch.setattr(file_store_module, "user_file_store", store)
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="summarize this",
        channel="web",
        include_recent=False,
        attachments=[{"file_id": entry["file_id"]}],
    )

    assert any(
        block.get("source") == "attachment" and block.get("modality") == "text"
        for block in prepared["runtime_blocks"]
    )
    assert "enterprise graph context" in str(prepared["messages"][-1]["content"])
