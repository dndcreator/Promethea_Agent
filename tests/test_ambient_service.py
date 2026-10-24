import asyncio
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentkit.tools.ambient import create_tools
from config import config
from gateway.ambient_service import AmbientService
from gateway.ambient_state import AmbientStore
from gateway.public_contracts import AmbientSettings, AmbientConfirmation, AmbientFeedback
from tests.test_agent_messages import inbox_host
from tests.test_background_agents import drain
from gateway.task_service import TaskExecutionConflict
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.runtime_event_log import RuntimeEventLog
from gateway.self_model_service import SelfModelService
from gateway.self_model_state import SelfModelStateStore
from agentkit.tools.standard.situation_tools import create_situation_tools
from agentkit.tools.subagent import DelegateTool


class Core:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.requests = []

    async def call_llm(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        action = self.actions.pop(0) if self.actions else {"action": "answer", "content": "No useful intervention."}
        return {"status": "success", "content": json.dumps(action)}


def setup(tmp_path, core):
    tasks, runtime, conversation, _, manager = inbox_host(tmp_path, core)
    conversation.self_model_service = SelfModelService(task_service=tasks, message_manager=manager, event_emitter=conversation.event_emitter, workspace_root=str(tmp_path))
    ambient = AmbientService(conversation=conversation, task_runtime=runtime, task_service=tasks, storage_path=tmp_path / "ambient.json")
    conversation.ambient_service = ambient
    runtime.register_driver("ambient", ambient)
    for tool in [*create_tools({}), *create_situation_tools(conversation.self_model_service)]:
        conversation.capability_service.register_tool(tool)
    return tasks, runtime, conversation, manager, ambient


def call(name, **args):
    return {"action": "tool_call", "tool_name": name, "args": args}


@pytest.mark.asyncio
async def test_opt_in_working_cognition_continuity_and_silence(tmp_path):
    core = Core(call("cognition.update_situation", expected_revision=0, attention=["Release readiness"], questions=["Did tests finish?"], interpretation="Unverified; inspect results next."))
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core)
    try:
        await drain(runtime)
        assert core.requests == []
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Help with release"))
        await drain(runtime)
        assert ambient.view("alice", "chat")["attention"] == ["Release readiness"]
        assert manager.get_messages("chat", user_id="alice") == []
        assert len(tasks.execution_tasks(run_type="ambient")) == 1
        restored = AmbientStore(tmp_path / "ambient.json")
        assert SelfModelStateStore(conversation.self_model_service.state.path).get("alice").questions == ["Did tests finish?"]
        assert "questions" not in restored.get("alice", "chat").model_dump()
        scene = ambient.store.get("alice", "chat")
        scene.next_check_at = time.time() - 1
        ambient.store.put(scene)
        await drain(runtime)
        await drain(runtime)
        assert "Did tests finish?" in str(core.requests[-1])
        assert len(tasks.execution_tasks(run_type="ambient")[0]["runs"]) == 2
        assert conversation.action_service.task_service is tasks
        prepared = await conversation.prepare_chat_turn(session_id="chat", user_id="alice", user_message="Continue", channel="web", run_context=ambient._context(tasks.execution_tasks(run_type="ambient")[0], tasks.execution_tasks(run_type="ambient")[0]["runs"][-1], {}, ambient.store.get("alice", "chat")))
        assert any("Did tests finish?" in str(row["content"]) for row in prepared["messages"])
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_exact_annotations_feedback_and_explicit_notice(tmp_path):
    core = Core()
    tasks, runtime, _, manager, ambient = setup(tmp_path, core)
    manager.add_message("chat", "assistant", "交付日期是周五。", "alice", sync_memory=False)
    message = manager.get_messages("chat", user_id="alice")[0]
    core.actions = [call("ambient.annotate", message_id=message["id"], selected_text="周五", start_offset=5, end_offset=7, title="时间约束", content="需要核对时区。"), call("ambient.say", content="我注意到交付日期需要核对时区。")]
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        notes = manager.get_session("chat", user_id="alice")["followups"]
        assert len(notes) == 1 and notes[0]["source"] == "agent"
        ambient.feedback("alice", "chat", AmbientFeedback(annotation_id=notes[0]["id"], decision="accepted"))
        assert manager.get_session("chat", user_id="alice")["followups"][0]["state"] == "accepted"
        assert manager.get_messages("chat", user_id="alice")[-1]["content"] == "我注意到交付日期需要核对时区。"
        with pytest.raises(KeyError):
            ambient.view("bob", "chat")
    finally:
        await runtime.shutdown()


def test_portability_never_grants_autonomy_and_persistence_rolls_back(tmp_path, monkeypatch):
    store = AmbientStore(tmp_path / "state.json")
    scene = store.get("alice", "chat")
    scene.settings.enabled = True
    store.put(scene)
    transferred = AmbientStore(tmp_path / "transfer.json")
    transferred.import_user_state("bob", store.export_user_state("alice"))
    assert not transferred.get("bob", "chat").settings.enabled
    monkeypatch.setattr(store, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    scene.settings.direction = "not persisted"
    with pytest.raises(OSError):
        store.put(scene)
    assert store.get("alice", "chat").settings.direction == ""


def test_projection_does_not_require_new_conversations_to_exist(tmp_path):
    _, _, _, _, ambient = setup(tmp_path, Core())
    assert ambient.self_model.working_context("alice")["revision"] == 0


@pytest.mark.asyncio
async def test_disable_revokes_and_daily_budget_bounds_cycles(tmp_path, monkeypatch):
    monkeypatch.setattr(config.ambient, "daily_cycles", 1)
    core = Core()
    tasks, runtime, _, _, ambient = setup(tmp_path, core)
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        scene = ambient.store.get("alice", "chat")
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        await drain(runtime)
        assert len(core.requests) == 1
        ambient.configure("alice", "chat", AmbientSettings(enabled=False))
        assert ambient.view("alice", "chat")["status"] == "disabled"
        assert tasks.execution_tasks(run_type="ambient")[0]["status"] == "paused"
    finally:
        await runtime.shutdown()


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.asyncio
async def test_sensitive_action_waits_for_exact_consent_and_continues_same_run(tmp_path, action):
    core = Core(call("test.send", recipient="someone"))
    tasks, runtime, conversation, _, ambient = setup(tmp_path, core)
    invoke = AsyncMock(return_value={"ok": True, "sent": True})
    conversation.capability_service.register_tool(SimpleNamespace(tool_id="test.send", name="test.send", description="Send a message", side_effect_level="external_write", invoke=invoke))
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        state = ambient.view("alice", "chat")
        assert state["status"] == "waiting_confirmation"
        invoke.assert_not_awaited()
        pending = state["pending"]
        command = AmbientConfirmation(run_id=pending["run_id"], tool_call_id=pending["tool_call_id"], action=action)
        ambient.configure("alice", "chat", AmbientSettings(enabled=False))
        assert ambient.view("alice", "chat")["pending"] is None
        with pytest.raises(PermissionError):
            await ambient.confirm("alice", "chat", command)
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        with pytest.raises(TaskExecutionConflict):
            await ambient.confirm("alice", "chat", command.model_copy(update={"tool_call_id": "forged"}))
        await ambient.confirm("alice", "chat", command)
        assert invoke.await_count == (1 if action == "approve" else 0)
        row = tasks.get_task(state["task_id"], user_id="alice")
        assert len(row["runs"]) == 1 and row["runs"][0]["status"] == "completed"
        assert len(row["runs"][0]["attempts"]) == 2
        with pytest.raises(TaskExecutionConflict):
            await ambient.confirm("alice", "chat", command)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_restarts_restore_same_completed_checkpoint_without_reexecuting(tmp_path):
    core = Core(call("cognition.update_situation", expected_revision=0, attention=["Release"], questions=[], interpretation="Next investigation"))
    tasks, runtime, _, _, ambient = setup(tmp_path, core)
    ambient.configure("alice", "chat", AmbientSettings(enabled=True))
    await drain(runtime)
    task = tasks.execution_tasks(run_type="ambient")[0]
    run = task["runs"][0]
    tasks.update_run(task_id=task["task_id"], user_id="alice", run_id=run["run_id"], status="running")
    await runtime.shutdown()
    count = len(core.requests)
    restored, restarted, _, _, service = setup(tmp_path, core)
    try:
        await restarted.recover_incomplete()
        await drain(restarted)
        assert len(core.requests) == count
        assert service.view("alice", "chat")["attention"] == ["Release"]
        assert restored.get_task(task["task_id"], user_id="alice")["runs"][0]["status"] == "completed"
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_durable_events_are_owner_scoped_deduped_and_reconstruct_evidence(tmp_path):
    tasks, runtime, conversation, _, _ = setup(tmp_path, Core())
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    conversation.event_emitter = EventEmitter(log)
    conversation.self_model_service.event_emitter = conversation.event_emitter
    conversation.event_emitter.on(EventType.GOAL_GAPS_UPDATED, conversation.self_model_service.observe)
    ambient = AmbientService(conversation=conversation, task_runtime=runtime, task_service=tasks, storage_path=tmp_path / "events-state.json")
    ambient.configure("alice", "chat", AmbientSettings(enabled=True))
    before = ambient.view("alice", "chat")["revision"]
    await conversation.event_emitter.emit(EventType.GOAL_GAPS_UPDATED, {"user_id": "bob", "session_id": "chat", "reason": "private"})
    assert ambient.view("alice", "chat")["revision"] == before
    await conversation.event_emitter.emit(EventType.GOAL_GAPS_UPDATED, {"user_id": "alice", "session_id": "chat", "reason": "a test failed", "token": "secret"})
    revision = ambient.view("alice", "chat")["revision"]
    ambient.recover()
    assert ambient.view("alice", "chat")["revision"] == revision
    projected = ambient.self_model.working_context("alice")
    assert "a test failed" in str(projected["changes"])
    assert "secret" not in str(projected["changes"])
    assert log.get_consumer_cursor("ambient.v1") == log.next_seq - 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_ambient_child_results_return_to_same_situation_without_forced_chat(tmp_path):
    core = Core(call("subagent.delegate", objective="Check material", label="Investigation", tools=[]))
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core)
    conversation.capability_service.register_tool(DelegateTool(SimpleNamespace(conversation_service=conversation)))
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "An important dependency is missing."})
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        root = tasks.execution_tasks(run_type="ambient")[0]
        child = tasks.execution_tasks(run_type="subagent")[0]
        assert child["metadata"]["delegation"]["parent_agent_task_id"] == root["task_id"]
        assert tasks.execution_tasks(run_type="agent_inbox") == []
        assert ambient.store.get("alice", "chat").last_trigger["event_type"] == "agent.reports"
        scene = ambient.store.get("alice", "chat")
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        await drain(runtime)
        assert "important dependency" in str(core.requests[-1])
        assert manager.get_messages("chat", user_id="alice") == []
        assert conversation.background_agents.messages.pending(user_id="alice", session_id="chat", agent_task_id=root["task_id"]) == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_disable_cancels_active_descendants_and_blocks_their_readmission(tmp_path):
    core = Core(call("subagent.delegate", objective="Investigate", label="Child", tools=[]))
    tasks, runtime, conversation, _, ambient = setup(tmp_path, core)
    conversation.capability_service.register_tool(DelegateTool(SimpleNamespace(conversation_service=conversation)))
    entered, release = asyncio.Event(), asyncio.Event()

    async def child(**kwargs):
        ambient.assert_execution()
        entered.set()
        await release.wait()
        return {"status": "success", "content": "done"}

    conversation.run_delegated_turn = child
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await runtime._recover_available()
        await asyncio.wait_for(entered.wait(), 2)
        ambient.configure("alice", "chat", AmbientSettings(enabled=False))
        await drain(runtime)
        task = tasks.execution_tasks(run_type="subagent")[0]
        assert task["status"] == "paused"
        assert not conversation.background_agents.available(task)
        with pytest.raises(PermissionError):
            ambient.descendant_authority(task)
    finally:
        release.set()
        await runtime.shutdown()
