import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import config
from gateway.ambient_state import AmbientStore
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.public_contracts import AmbientSettings
from gateway.runtime_event_log import RuntimeEventLog
from gateway.self_model_service import SelfModelService
from gateway.http.routes import status
from tests.test_ambient_service import Core, call, setup
from tests.test_background_agents import drain
from tests.test_background_agents import parent
from gateway.delegation import DelegationRequest


@pytest.mark.asyncio
async def test_one_identity_spans_sessions_and_observes_the_whole_owned_space(tmp_path):
    core = Core()
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core)
    manager.create_session("other", user_id="alice")
    manager.create_session("private", user_id="bob")
    manager.add_message("other", "user", "another project", "alice", sync_memory=False)
    manager.add_message("private", "user", "private secret", "bob", sync_memory=False)
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Keep the whole project in mind"))
        await drain(runtime)
        first = ambient.view("alice", "chat")
        assert ambient.view("alice", "other") == first
        assert ambient.view("alice", None) == first
        assert len(ambient.store.scenes) == 1
        assert "another project" in str(core.requests[0])
        assert "private secret" not in str(core.requests[0])
        ambient.configure("alice", "other", AmbientSettings(enabled=True, direction="Keep the whole project in mind"))
        await drain(runtime)
        await drain(runtime)
        assert ambient.view("alice", "other")["task_id"] == first["task_id"]
        assert len(tasks.execution_tasks(run_type="ambient")) == 1
    finally:
        await runtime.shutdown()


def test_old_session_states_converge_once_without_dual_writes(tmp_path):
    path = tmp_path / "ambient.json"
    first = {"user_id": "alice", "session_id": "a", "attention": ["A"], "revision": 1}
    second = {"user_id": "alice", "session_id": "b", "attention": ["B"], "revision": 2}
    path.write_text(json.dumps({"version": 1, "situations": {"a": first, "b": second}, "usage": {}}), encoding="utf-8")
    model = SelfModelService(workspace_root=str(tmp_path))
    restored = AmbientStore(path, cognition_store=model.state)
    assert len(restored.scenes) == 1
    assert model.state.get("alice").attention == ["B", "A"]
    assert restored.get("alice", "b").session_id == "b"
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3
    assert "attention" not in json.loads(path.read_text(encoding="utf-8"))["situations"]["alice"]


@pytest.mark.asyncio
async def test_root_turns_share_identity_while_children_can_progress_in_parallel(tmp_path):
    _, runtime, conversation, _, _ = setup(tmp_path, Core())
    entered = asyncio.Event()

    async def another_conversation():
        async with conversation.agent_execution("alice", "other"):
            entered.set()

    try:
        async with conversation.agent_execution("alice", "chat"):
            other = asyncio.create_task(another_conversation())
            await asyncio.sleep(0)
            assert not entered.is_set()
            async with conversation.agent_execution("alice", "other", "child"):
                assert conversation.agent_is_active("alice", "chat")
        await other
        assert entered.is_set()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_deleted_transcript_does_not_destroy_personal_attention(tmp_path):
    core = Core(call("cognition.update_situation", expected_revision=0, attention=["Project"], questions=[], interpretation="Continue checking results"))
    tasks, runtime, _, manager, ambient = setup(tmp_path, core)
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        identity = ambient.view("alice", None)["task_id"]
        manager.delete_session("chat", user_id="alice")
        scene = ambient.store.get("alice")
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        await drain(runtime)
        assert ambient.view("alice", None)["task_id"] == identity
        assert ambient.view("alice", None)["attention"] == ["Project"]
        assert manager.get_messages("chat", user_id="alice") == []
        assert len(tasks.execution_tasks(run_type="ambient")) == 1
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_welcome_consumes_identity_cognition_and_scoped_state_with_receipts(tmp_path, monkeypatch):
    class WelcomeCore:
        def __init__(self):
            self.requests = []

        async def call_llm(self, messages, **kwargs):
            self.requests.append(messages)
            return {"status": "success", "content": json.dumps({"greeting": "你好。", "context_hint": "文章可以继续整理。", "suggested_actions": ["继续文章"]})}

    core = WelcomeCore()
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core)
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    conversation.event_emitter = EventEmitter(log)
    tasks.create_task(user_id="alice", title="Release blocker", objective="Verify packaging")
    tasks.create_task(user_id="bob", title="PRIVATE BOB TASK", objective="secret")

    class Memory:
        def list_entries(self, *, user_id, **kwargs):
            assert user_id == "alice"
            return {"ok": True, "entries": [{"memory_id": "pref", "content": "Concise technical writing", "memory_type": "preference", "status": "active"}]}

        def list_write_proposals(self, *, user_id, **kwargs):
            assert user_id == "alice"
            return []

    workflows = SimpleNamespace(list_runs=lambda *, user_id, limit: [{"workflow_run_id": "wf", "status": "paused", "session_id": "chat"}] if user_id == "alice" else [])
    model = SelfModelService(memory_service=Memory(), task_service=tasks, message_manager=manager, workflow_engine=workflows, workspace_root=str(tmp_path))
    model.ambient_service = ambient
    model.agent_messages = conversation.background_agents.messages
    conversation.self_model_service = model
    cfg = config.model_dump()
    cfg.setdefault("persona", {}).setdefault("soul", {})["content"] = "SOUL_STYLE_MARKER"
    cfg["system_prompt"] = "CUSTOM_STYLE_MARKER"
    conversation._get_user_prompt_and_config = AsyncMock(return_value=("CORE_IDENTITY_MARKER", cfg))
    gateway = SimpleNamespace(conversation_service=conversation, message_manager=manager, self_model_service=model)
    monkeypatch.setattr(status, "get_gateway_server", lambda: gateway)
    monkeypatch.setattr(status.user_manager, "get_user_by_id", lambda user: {"username": "Alice", "agent_name": "Promethea"})
    monkeypatch.setattr(status.user_manager, "get_user_config", lambda user: {})
    try:
        a = await status.get_dynamic_welcome(lang="zh", visit_id="visit", user_id="alice")
        b = await status.get_dynamic_welcome(lang="zh", visit_id="visit", user_id="alice")
        assert a == b and a["generated_by"] == "llm"
        assert len(core.requests) == 1
        seen = str(core.requests[0])
        for value in ("CORE_IDENTITY_MARKER", "SOUL_STYLE_MARKER", "CUSTOM_STYLE_MARKER", "Concise technical writing", "Release blocker"):
            assert value in seen
        assert "PRIVATE BOB TASK" not in seen
        assert log.query(user_id="alice", event_type=EventType.AGENT_COMMUNICATION_OFFERED.value)
        admission = conversation.background_agents.messages.communication_admission("alice", "Another unsolicited update", delivery_id="next")
        assert admission["status"] == "deferred"
        assert conversation.background_agents.messages.communication_admission("bob", "Another unsolicited update", delivery_id="next")["allowed"]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_autonomous_schedules_keep_revocable_origin_authority(tmp_path):
    from agentkit.mcp.invocation_context import bind_invocation_context
    from gateway.temporal_scheduler import TemporalSchedulerService

    core = Core(call("test.schedule"))
    _, runtime, conversation, _, ambient = setup(tmp_path, core)
    capability = conversation.capability_service
    capability.autonomy_validator = ambient.validate_scheduled_scope
    scheduler = TemporalSchedulerService(workspace_root=str(tmp_path))
    scheduler.configure_tool_runtime(executor=capability._execute_managed_tool, confirmation_resolver=capability.requires_confirmation)
    read = AsyncMock(return_value={"ok": True})

    async def schedule(args, ctx):
        return await scheduler.create_job("autonomous", interval_seconds=60, service_name="test", tool_name="read")

    capability.register_tool(SimpleNamespace(tool_id="test.schedule", name="test.schedule", description="Schedule investigation", side_effect_level="workspace_write", invoke=schedule))
    capability.register_tool(SimpleNamespace(tool_id="test.read", name="test.read", description="Inspect", side_effect_level="read_only", invoke=read))
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        autonomous = scheduler._load_jobs()[0]
        assert autonomous["execution_context"]["ambient_scope"]["task_id"] == ambient.view("alice", None)["task_id"]
        with bind_invocation_context({"user_id": "alice", "session_id": "chat"}):
            await scheduler.create_job("explicit", interval_seconds=60, service_name="test", tool_name="read")
        ambient.configure("alice", None, AmbientSettings(enabled=False))
        result = await scheduler.run_due_jobs_internal(now_ts=time.time() + 61)
        assert sum(row["ok"] for row in result["ran"]) == 1
        assert read.await_count == 1
        assert scheduler._load_jobs()[0]["status"] == "paused"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_deferred_notice_uses_existing_ipc_outbox_and_survives_until_reconsidered(tmp_path, monkeypatch):
    core = Core(call("ambient.say", content="The packaging check needs attention."))
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core)
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    conversation.event_emitter = EventEmitter(log)
    messages = conversation.background_agents.messages
    await messages.record_communication(user_id="alice", session_id=None, kind="welcome", content="Welcome back.", delivery_id="welcome")
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await drain(runtime)
        assert manager.get_messages("chat", user_id="alice") == []
        retained = messages.pending_communications("alice")
        assert retained[0]["content"] == "The packaging check needs attention."
        assert messages.pending_communications("bob") == []
        assert tasks.get_task(retained[0]["task_id"], user_id="alice")["runs"][0]["metadata"]["agent_outbox"]
        monkeypatch.setattr(config.ambient, "communication_cooldown_s", 0)
        core.actions = [call("ambient.say", content=retained[0]["content"])]
        scene = ambient.store.get("alice")
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        await drain(runtime)
        assert [row["content"] for row in manager.get_messages("chat", user_id="alice")] == [retained[0]["content"]]
        assert messages.pending_communications("alice") == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_parallel_reports_from_different_conversations_share_one_root_delivery(tmp_path):
    core = Core()
    tasks, runtime, conversation, manager, _ = setup(tmp_path, core)
    manager.create_session("other", user_id="alice")
    background = conversation.background_agents

    async def child(**kwargs):
        return {"status": "success", "content": kwargs["label"] + " evidence"}

    conversation.run_delegated_turn = child
    try:
        async with conversation.agent_execution("alice", "chat"):
            for session, label in (("chat", "A"), ("other", "B")):
                with conversation.delegation.turn():
                    await background.start(DelegationRequest(objective="Inspect", label=label, tools=[]), parent=parent(session=session), user_config=config.model_dump())
            await drain(runtime)
            assert core.requests == []
        await drain(runtime)
        assert len(core.requests) == 1
        assert "A evidence" in str(core.requests[0]) and "B evidence" in str(core.requests[0])
        assert len(tasks.execution_tasks(run_type="agent_inbox")) == 1
        assert background.messages.pending(user_id="alice", session_id=None) == []
    finally:
        await runtime.shutdown()
