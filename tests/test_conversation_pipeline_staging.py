from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.conversation_pipeline import (
    run_staged_pipeline,
    stage_input_normalization,
    stage_mode_detection,
)
from gateway.conversation_service import ConversationService
from gateway.http.user_file_store import UserFileStore
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


class _DummyWorkflowEngine:
    def __init__(self):
        self.defined = []
        self.started = []

    def define_workflow(self, definition):
        self.defined.append(definition)
        return definition

    def start_workflow(self, **kwargs):
        self.started.append(kwargs)
        return SimpleNamespace(workflow_run_id="wf_run_test")


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
    assert "[记忆]" not in out.content
    assert (out.raw.get("memory_visibility") or {}).get("enabled") is True
    capability_state = out.raw.get("capability_state") or {}
    assert capability_state.get("degraded") is False
    assert capability_state.get("memory", {}).get("status") == "ok"


@pytest.mark.asyncio
async def test_pipeline_exposes_memory_visibility_feedback():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service._should_recall_memory = AsyncMock(return_value=False)
    memory = MagicMock()
    memory.is_enabled.return_value = True
    memory.drain_visibility_hints.return_value = [
        {
            "type": "memory_saved",
            "memory_type": "preference",
            "content_preview": "prefer concise answers",
        }
    ]
    service.memory_service = memory

    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )

    mv = out.raw.get("memory_visibility") or {}
    assert mv.get("enabled") is True
    assert "已记住" in str(mv.get("write_notice") or "")
    assert "[记忆]" not in out.content


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
    assert "identity" in prompt_debug["used_block_ids"]
    assert "persona_core" not in prompt_debug["used_block_ids"]
    assert "soul_core" in prompt_debug["used_block_ids"]


@pytest.mark.asyncio
async def test_prepare_chat_turn_uses_prompt_assembler_blocks():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="hello world",
        channel="web",
        include_recent=False,
    )

    prompt_debug = prepared.get("prompt_assembly") or {}
    used_block_ids = prompt_debug.get("used_block_ids") or []
    assert "identity" in used_block_ids
    assert "runtime_context" in used_block_ids
    assert "persona_core" not in used_block_ids
    assert "soul_core" in used_block_ids
    assert prepared["messages"][0]["role"] == "system"
    assert "Current local date" in prepared["messages"][0]["content"]
    assert "Soul Prompt" in prepared["messages"][0]["content"]


@pytest.mark.asyncio
async def test_prepare_chat_turn_keeps_core_identity_when_agent_name_is_customized():
    config_service = MagicMock()
    config_service.get_merged_config.return_value = {
        "agent_name": "EDI",
        "system_prompt": "Speak in a calm tactical style.",
        "prompts": {"Promethea_system_prompt": "You are Promethea."},
    }
    service = ConversationService(
        conversation_core=_DummyCore(),
        event_emitter=None,
        config_service=config_service,
    )
    service.route_prompt_policy = AsyncMock(
        return_value={
            "mode": "fast",
            "cognitive_mode": "direct",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": False,
            "reason": "test",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="Are you Promethea?",
        channel="web",
        include_recent=False,
    )

    system_prompt = prepared["messages"][0]["content"]
    used_block_ids = (prepared.get("prompt_assembly") or {}).get("used_block_ids") or []
    assert "You are Promethea" in system_prompt
    assert "You are EDI" not in system_prompt
    assert "Active display name: EDI" in system_prompt
    assert "Speak in a calm tactical style" in system_prompt
    assert "customization" in used_block_ids


@pytest.mark.asyncio
async def test_prepare_chat_turn_wraps_legacy_core_prompt_with_identity_layering():
    legacy_prompt = (
        "You are Promethea, a cognitive agent runtime assistant. "
        "Promethea is a runtime with graph/layered long-term memory."
    )
    config_service = MagicMock()
    config_service.get_merged_config.return_value = {
        "agent_name": "EDI",
        "system_prompt": "",
        "prompts": {"Promethea_system_prompt": legacy_prompt},
    }
    service = ConversationService(
        conversation_core=_DummyCore(),
        event_emitter=None,
        config_service=config_service,
    )
    service.route_prompt_policy = AsyncMock(
        return_value={
            "mode": "fast",
            "cognitive_mode": "direct",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": False,
            "reason": "test",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="Any new answer now?",
        channel="web",
        include_recent=False,
    )

    system_prompt = prepared["messages"][0]["content"]
    assert "Core identity:" in system_prompt
    assert "Presentation and roleplay layers:" in system_prompt
    assert "prior mistakes" in system_prompt
    assert "Additional user/default prompt:" in system_prompt
    assert legacy_prompt in system_prompt


@pytest.mark.asyncio
async def test_prepare_chat_turn_injects_tool_protocol_when_policy_needs_tools():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service.route_prompt_policy = AsyncMock(
        return_value={
            "mode": "fast",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": True,
            "reason": "test",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="calculate this with a tool",
        channel="web",
        include_recent=False,
    )

    prompt_debug = prepared.get("prompt_assembly") or {}
    used_block_ids = prompt_debug.get("used_block_ids") or []
    system_prompt = prepared["messages"][0]["content"]
    assert "tools" in used_block_ids
    assert "Tool execution protocol" in system_prompt
    assert "Never claim a tool ran" in system_prompt
    assert "Runtime registered tools (structured JSON)" in system_prompt


@pytest.mark.asyncio
async def test_prepare_chat_turn_light_action_does_not_start_reasoning_tree():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    reasoning = MagicMock()
    reasoning.is_enabled.return_value = True
    reasoning.run = AsyncMock(side_effect=AssertionError("light action should not run full reasoning"))
    service.reasoning_service = reasoning
    service.route_prompt_policy = AsyncMock(
        return_value={
            "source": "test",
            "cognitive_mode": "light_action",
            "mode": "fast",
            "reasoning_budget": "small",
            "tool_budget": 3,
            "memory_budget": "brief",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": True,
            "reason": "simple lookup",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="查一下茅台最新股价",
        channel="web",
        include_recent=False,
    )

    assert prepared["reasoning"]["used_reasoning"] is False
    assert prepared["prompt_policy"]["cognitive_mode"] == "light_action"
    assert prepared["execution_budget"]["tool_budget"] == 3
    assert "tools" in (prepared.get("prompt_assembly") or {}).get("used_block_ids", [])


@pytest.mark.asyncio
async def test_fast_mode_prompt_blocks_do_not_include_reasoning():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="quick hello", session_id="s1", user_id="u1")
    )

    prompt_debug = out.raw.get("prompt_assembly") or {}
    used_block_ids = prompt_debug.get("used_block_ids") or []
    assert "reasoning" not in used_block_ids


@pytest.mark.asyncio
async def test_pipeline_attaches_plan_workflow_trace(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service.workflow_engine = _DummyWorkflowEngine()

    reasoning = MagicMock()
    reasoning.is_enabled.return_value = True
    reasoning.run = AsyncMock(
        return_value={
            "used_reasoning": True,
            "tree_id": "tree_1",
            "system_prompt": "sys",
            "plan_steps": [
                {
                    "title": "Collect data",
                    "goal": "Fetch required information",
                    "requires_tools": True,
                    "tool_intent": "search",
                }
            ],
        }
    )
    service.reasoning_service = reasoning

    async def _deep_mode(_svc, _normalized):
        return ModeDecision(mode="workflow", reason="test", confidence=1.0)

    monkeypatch.setattr("gateway.conversation_pipeline.stage_mode_detection", _deep_mode)

    out = await service.run_conversation(
        ConversationRunInput(user_message="please do a workflow plan", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    trace = out.raw.get("workflow_trace")
    assert isinstance(trace, dict)
    assert trace.get("workflow_run_id") == "wf_run_test"
    assert len(service.workflow_engine.defined) == 1
    assert len(service.workflow_engine.started) == 1


@pytest.mark.asyncio
async def test_pipeline_normalizes_plan_step_boolean_strings(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service.workflow_engine = _DummyWorkflowEngine()

    reasoning = MagicMock()
    reasoning.is_enabled.return_value = True
    reasoning.run = AsyncMock(
        return_value={
            "used_reasoning": True,
            "tree_id": "tree_2",
            "system_prompt": "sys",
            "plan_steps": [
                {
                    "title": "Do step",
                    "goal": "Do goal",
                    "requires_tools": "false",
                    "requires_memory": "true",
                }
            ],
        }
    )
    service.reasoning_service = reasoning

    async def _deep_mode(_svc, _normalized):
        return ModeDecision(mode="workflow", reason="test", confidence=1.0)

    monkeypatch.setattr("gateway.conversation_pipeline.stage_mode_detection", _deep_mode)

    out = await service.run_conversation(
        ConversationRunInput(user_message="workflow bool normalize", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    definition = service.workflow_engine.defined[0]
    step_inputs = definition.steps[0].inputs
    assert step_inputs["requires_tools"] is False
    assert step_inputs["requires_memory"] is True


@pytest.mark.asyncio
async def test_pipeline_exposes_stage_status_and_degraded_reason_when_memory_empty(monkeypatch):
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service._should_recall_memory = AsyncMock(return_value=True)
    memory = MagicMock()
    memory.is_enabled.return_value = True
    memory.get_context = AsyncMock(return_value="")
    service.memory_service = memory

    out = await service.run_conversation(
        ConversationRunInput(user_message="need memory context", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    pipeline = out.raw.get("pipeline") or {}
    stage_status = pipeline.get("stage_status") or {}
    memory_status = stage_status.get("memory_recall") or {}
    assert memory_status.get("status") == "degraded"
    assert memory_status.get("reason_code") == "empty_context"
    capability = out.raw.get("capability_state") or {}
    assert capability.get("degraded") is True
    assert "memory_recall" in (capability.get("degraded_stages") or [])

@pytest.mark.asyncio
async def test_pipeline_exposes_task_graph_and_context_budget_contracts():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)

    out = await service.run_conversation(
        ConversationRunInput(user_message="contract check", session_id="s1", user_id="u1")
    )

    assert out.status == "success"
    task_graph = out.raw.get("task_graph") or {}
    assert task_graph.get("version") == "1.0"
    assert isinstance(task_graph.get("nodes"), list)
    assert isinstance(task_graph.get("edges"), list)
    assert task_graph.get("current_node_id")

    context_budget = out.raw.get("context_budget") or {}
    assert context_budget.get("version") == "1.0"
    assert "compacted" in context_budget
    assert isinstance(context_budget.get("used_block_ids"), list)
    orchestration = out.raw.get("orchestration") or {}
    assert orchestration.get("version") == "1.0"
    assert orchestration.get("execution_core") == "single_loop_runtime"
    assert isinstance(orchestration.get("reasoning_engine"), dict)


@pytest.mark.asyncio
async def test_prepare_chat_turn_compiles_text_attachment_as_runtime_block(tmp_path, monkeypatch):
    import gateway.http.user_file_store as file_store_module

    store = UserFileStore(root_dir=str(tmp_path))
    entry = store.save_upload(
        user_id="u1",
        filename="notes.txt",
        content=b"enterprise graph context",
        content_type="text/plain",
        session_id="s1",
    )
    monkeypatch.setattr(file_store_module, "user_file_store", store)

    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    service.route_prompt_policy = AsyncMock(
        return_value={
            "mode": "fast",
            "cognitive_mode": "direct",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": False,
            "reason": "test",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="summarize this",
        channel="web",
        include_recent=False,
        attachments=[{"file_id": entry["file_id"]}],
    )

    user_content = prepared["messages"][-1]["content"]
    assert isinstance(user_content, str)
    assert "summarize this" in user_content
    assert "enterprise graph context" in user_content
    assert prepared["llm_io"]["input_block_count"] >= 2
    assert any(
        row.get("source") == "attachment" and row.get("modality") == "text"
        for row in prepared["runtime_blocks"]
    )


@pytest.mark.asyncio
async def test_prepare_chat_turn_compiles_image_attachment_for_vision_model(tmp_path, monkeypatch):
    import gateway.http.user_file_store as file_store_module

    store = UserFileStore(root_dir=str(tmp_path))
    entry = store.save_upload(
        user_id="u1",
        filename="diagram.png",
        content=b"fake image bytes",
        content_type="image/png",
        session_id="s1",
    )
    monkeypatch.setattr(file_store_module, "user_file_store", store)

    config_service = MagicMock()
    config_service.get_merged_config.return_value = {
        "vision_enabled": True,
        "api": {"model": "gpt-4o"},
        "prompts": {"Promethea_system_prompt": "Promethea system"},
    }
    service = ConversationService(
        conversation_core=_DummyCore(),
        event_emitter=None,
        config_service=config_service,
    )
    service.route_prompt_policy = AsyncMock(
        return_value={
            "mode": "fast",
            "cognitive_mode": "direct",
            "need_reasoning": False,
            "need_memory": False,
            "need_tools": False,
            "reason": "test",
            "confidence": 0.9,
        }
    )

    prepared = await service.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="what is in this image?",
        channel="web",
        include_recent=False,
        attachments=[{"file_id": entry["file_id"]}],
    )

    user_content = prepared["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert any(part.get("type") == "text" for part in user_content)
    assert any(part.get("type") == "image_url" for part in user_content)
    assert prepared["llm_io"]["vision_enabled"] is True
