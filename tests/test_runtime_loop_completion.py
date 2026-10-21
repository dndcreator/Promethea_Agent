from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.observation import RuntimeObservation
from gateway.capability_service import CapabilityService, ToolInvocationContext
from gateway.conversation_service import ConversationService
from gateway.events import EventEmitter
from agentkit.tools.standard.runtime_tools import RuntimeReadObservationTool
from gateway.prompt_assembler import PromptAssembler
from gateway.protocol import EventType
from gateway.runtime_event_log import RuntimeEventLog
from gateway.runtime_io import ContextCompiler
from gateway.tool_prompt_blocks import CAPABILITIES_HEADER
from gateway.tools.registry import ToolRegistry
from gateway.tools.spec import ToolSpec


class Core:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.requests = []

    async def call_llm(self, messages, **_kwargs):
        self.requests.append(messages)
        action = next(self.actions)
        return {"status": "success", "content": json.dumps(action(messages) if callable(action) else action)}


def capabilities():
    return CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}))


def register(service, name, **attributes):
    tool = SimpleNamespace(tool_id=name, name=name, description=name, input_schema={"type": "object"},
                           side_effect_level="read_only", **attributes)
    service.register_tool(tool)


@pytest.mark.asyncio
async def test_model_sees_new_registry_revision_and_schema_after_tool_publication():
    service = capabilities()
    register(service, "tools.publish")

    def next_step(messages):
        projections = [message["content"] for message in messages if message.get("role") == "system"
                       and str(message.get("content")).startswith(CAPABILITIES_HEADER)]
        assert len(projections) == 1
        assert '"name":"generated.new"' in projections[0]
        return {"action": "tool_call", "tool_name": "generated.new", "args": {}}

    core = Core([
        {"action": "tool_call", "tool_name": "tools.publish", "args": {}}, next_step,
        {"action": "answer", "content": "Created and used the new tool."},
    ])
    emitter = EventEmitter()
    action = ActionService(conversation_core=core, capability_service=service, event_emitter=emitter)
    conversation = ConversationService(conversation_core=core, action_service=action, capability_service=service)
    context = SimpleNamespace(user_id="u", prompt_blocks={})

    def execute(name, _args):
        if name == "tools.publish":
            register(service, "generated.new")
        return {"tool": name}

    out = await conversation.run_chat_loop([{"role": "user", "content": "create a tool"}],
        user_id="u", run_context=context, tool_executor=execute, max_recursion=4)
    assert out["status"] == "success"
    assert all("generated.new" not in str(message.get("content")) for message in core.requests[0])
    assert [item["tool_name"] for item in out["execution_path"]] == ["tools.publish", "generated.new"]
    manifests = [event.payload for event in emitter._event_history if event.event == EventType.MODEL_CALL_RECORDED]
    assert len({item["capability_snapshot_id"] for item in manifests}) == 2
    assert manifests[1]["capability_snapshot_id"] == manifests[2]["capability_snapshot_id"]
    assert manifests[0]["prompt_block_hashes"]["tools"] != manifests[1]["prompt_block_hashes"]["tools"]


@pytest.mark.asyncio
async def test_capability_diagnostics_preserve_unavailable_tools_without_offering_them_as_callable():
    service = capabilities()
    service.capability_provider = lambda: {"browser": {"ready": False, "reason": "dependency_missing"}}
    register(service, "browser.open", requires_capability="computer.browser")
    inspection = service.inspect_capabilities(["browser.open"])
    assert inspection["items"][0]["callable_now"] is False
    assert inspection["items"][0]["callable_reason"] == "dependency_missing"
    resolved = await service.resolve_capability_intent({"objective": "browse", "required_capabilities": ["computer.browser"]})
    assert resolved["candidates"] == []
    assert resolved["unavailable_candidates"][0]["callable_reason"] == "computer.browser:dependency_missing"
    assert service.inspect_capabilities(["unknown.tool"])["items"][0]["callable_now"] is False


def test_tool_context_refresh_replaces_only_its_owned_system_message():
    original = [
        {"role": "system", "content": "Core identity and immutable safety instructions."},
        {"role": "system", "content": CAPABILITIES_HEADER + "old"},
        {"role": "user", "content": CAPABILITIES_HEADER + "user text is not a Runtime block"},
    ]
    updated = PromptAssembler.refresh_tool_message(original, tools=[], snapshot={}, run_context=None)
    updated = PromptAssembler.refresh_tool_message(updated, tools=[], snapshot={}, run_context=None)
    assert len(updated) == 3
    assert updated[0] == original[0] and updated[-1] == original[-1]
    assert original[1]["content"].endswith("old")


def test_observation_projection_preserves_ids_status_and_original_data():
    observation = RuntimeObservation(action_loop_id="a", model_step_id="s", tool_call_id="c", tool_name="search",
        ok=True, structured_result={"body": "source content " * 10000})
    original = observation.model_content()
    messages = [{"role": "system", "content": "unchanged"}, {"role": "user", "content": original}]
    projected = ContextCompiler.project_observations(messages, [observation.as_dict()], per_result_chars=1000, total_chars=2000)
    fact = json.loads(projected[-1]["content"][0]["text"])
    assert fact["observation_id"] == observation.observation_id and fact["status"] == "completed"
    assert fact["result"]["truncated"] is True
    assert fact["result"]["read_more"]["tool_name"] == "runtime.read_observation"
    assert len(fact["result"]["preview"]) == 1000
    assert messages[-1]["content"] == original and "truncated" not in observation.structured_result


def test_loop_controls_follow_existing_nested_env_configuration(monkeypatch):
    from config import PrometheaConfig

    monkeypatch.setenv("ACTION__MAX_PARALLEL_TOOL_CALLS", "2")
    monkeypatch.setenv("ACTION__OBSERVATION_CHARS", "2000")
    monkeypatch.setenv("ACTION__OBSERVATION_HISTORY_CHARS", "12000")
    policy = PrometheaConfig().action
    assert (policy.max_parallel_tool_calls, policy.observation_chars, policy.observation_history_chars) == (2, 2000, 12000)


@pytest.mark.asyncio
async def test_legacy_truncated_observation_remains_explicitly_truncated(tmp_path):
    log = RuntimeEventLog(storage_path=str(tmp_path / "runtime.jsonl"))
    log.append(event_type=EventType.ACTION_OBSERVATION_COMMITTED.value, payload={
        "user_id": "u", "observation_id": "legacy", "structured_result": None,
        "model_projection": {"truncated": True, "preview": "retained prefix", "content_hash": "old"},
    })
    tool = RuntimeReadObservationTool(gateway_server=SimpleNamespace(event_emitter=EventEmitter(log)))
    page = await tool.invoke({"observation_id": "legacy"}, ToolInvocationContext(user_id="u"))
    assert page["source_truncated"] is True
    assert json.loads(page["content"])["preview"] == "retained prefix"


@pytest.mark.asyncio
async def test_large_result_can_be_read_back_after_restart_but_not_by_another_owner(tmp_path):
    log_path = str(tmp_path / "runtime.jsonl")
    emitter = EventEmitter(RuntimeEventLog(storage_path=log_path))
    core = Core([{"action": "tool_call", "tool_name": "web.fetch", "args": {}},
                 {"action": "answer", "content": "Fetched the content."}])
    action = ActionService(conversation_core=core, event_emitter=emitter)
    conversation = ConversationService(conversation_core=core, action_service=action)
    source = "BEGIN" + "x" * 50000 + "END"
    out = await conversation.run_chat_loop([{"role": "user", "content": "fetch"}], user_id="u", session_id="s",
        tool_executor=lambda *_: {"body": source, "api_key": "secret"})
    fact = json.loads(core.requests[1][-1]["content"][0]["text"])
    assert fact["result"]["truncated"] is True
    assert out["observations"][0]["structured_result"]["body"] == source
    tool = RuntimeReadObservationTool(gateway_server=SimpleNamespace(event_emitter=EventEmitter(RuntimeEventLog(storage_path=log_path))))
    observation_id = out["observations"][0]["observation_id"]
    content = []
    offset = 0
    while True:
        page = await tool.invoke({"observation_id": observation_id, "offset": offset, "max_chars": 12000}, ToolInvocationContext(user_id="u"))
        content.append(page["content"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    retained = json.loads("".join(content))
    assert retained == {"body": source, "api_key": "[REDACTED]"}
    with pytest.raises(FileNotFoundError):
        await tool.invoke({"observation_id": observation_id}, ToolInvocationContext(user_id="other"))
    with pytest.raises(PermissionError):
        await tool.invoke({"observation_id": observation_id})


@pytest.mark.asyncio
async def test_parallel_pool_is_bounded_and_exclusive_calls_form_barriers():
    registry = ToolRegistry()
    names = ["p1", "p2", "p3", "write", "p4", "p5"]
    for name in names:
        registry.register_spec(ToolSpec(tool_name=name, concurrency_safe=name != "write"))
    core = Core([{"action": "tool_calls", "calls": [{"tool_name": name, "args": {}} for name in names]},
                 {"action": "answer", "content": "done"}])
    active = set()
    peak = 0
    completed = []

    async def executor(name, _args):
        nonlocal peak
        if name == "write":
            assert not active and completed == ["p1", "p2", "p3"]
        elif name in {"p4", "p5"}:
            assert "write" in completed
        active.add(name)
        peak = max(peak, len(active))
        await asyncio.sleep(0.01)
        active.remove(name)
        completed.append(name)
        return {"name": name}

    out = await ActionService(conversation_core=core, capability_service=SimpleNamespace(tool_registry=registry)).run_action(
        goal="batch", messages=[], tool_executor=executor, user_config={"action": {"max_parallel_tool_calls": 2}})
    assert out["status"] == "success" and peak == 2
    assert [item["tool_name"] for item in out["observations"]] == names


@pytest.mark.asyncio
async def test_batch_cancellation_preserves_completed_and_marks_undispatched_calls(tmp_path):
    core = Core([{"action": "tool_calls", "calls": [{"id": name, "tool_name": name, "args": {}}
                                                     for name in ("done", "blocked", "never")]}])
    entered = asyncio.Event()
    executed = []

    async def executor(name, _args):
        executed.append(name)
        if name == "blocked":
            entered.set()
            await asyncio.Event().wait()
        return {"done": True}

    log = RuntimeEventLog(storage_path=str(tmp_path / "runtime.jsonl"))
    service = ActionService(conversation_core=core, event_emitter=EventEmitter(log))
    task = asyncio.create_task(service.run_action(goal="batch", messages=[], user_id="u", tool_executor=executor))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    records = log.query(user_id="u", event_type=EventType.ACTION_OBSERVATION_COMMITTED.value)
    assert executed == ["done", "blocked"]
    assert records[0]["payload"]["ok"] is True
    assert records[1]["payload"]["error"]["code"] == "TOOL_INTERRUPTED"
    assert records[2]["payload"]["error"]["code"] == "TOOL_NOT_EXECUTED"
