"""Real scheduler, registry, durable bus and Ambient; only model/source I/O scripted."""
from copy import deepcopy
import json
import time
from types import SimpleNamespace

import pytest

from agentkit.mcp.invocation_context import bind_invocation_context
from agentkit.tools.standard.schedule_tools import RuntimeScheduleTool
from agentkit.tools.standard.runtime_tools import RuntimeReadEventTool
from gateway.ambient_service import OBSERVED_EVENTS
from gateway.capability_service import ToolInvocationContext
from gateway.events import EventEmitter
from gateway.kernel_scheduler_service import KernelSchedulerService
from gateway.protocol import EventType
from gateway.public_contracts import AmbientSettings
from gateway.runtime_event_log import RuntimeEventLog
from gateway.temporal_scheduler import TemporalSchedulerService
from tests.test_ambient_service import Core, setup
from tests.test_background_agents import drain


class Source:
    tool_id = name = "example.changes"
    description = "Read actual source versions"
    side_effect_level = "read_only"
    observation_source = True

    def __init__(self):
        self.items = []
        self.calls = 0

    async def invoke(self, args, ctx=None):
        self.calls += 1
        return {"observations": deepcopy(self.items), "cursor": {"call": self.calls}}


def host_at(tmp_path, core=None):
    tasks, runtime, conversation, manager, ambient = setup(tmp_path, core or Core())
    emitter = EventEmitter(event_log=RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl")))
    conversation.event_emitter = conversation.action_service.event_emitter = emitter
    conversation.capability_service.event_emitter = emitter
    ambient.event_log = emitter.event_log
    ambient.self_model.event_emitter = emitter
    for event in OBSERVED_EVENTS:
        emitter.on(event, ambient._observe)
        emitter.on(event, ambient.self_model.observe)
    source = Source()
    conversation.capability_service.register_tool(source)
    kernel = KernelSchedulerService(workspace_root=str(tmp_path), capability_service=conversation.capability_service)
    server = SimpleNamespace(kernel_scheduler=kernel, event_emitter=emitter)
    conversation.capability_service.register_tool(RuntimeScheduleTool(server))
    return tasks, runtime, conversation, manager, ambient, source, kernel, server


async def schedule(conversation, *, user="alice"):
    return await conversation.capability_service.call_tool("runtime.schedule", {
        "name": "Watch reliability", "service_name": "example", "tool_name": "changes",
        "interval_seconds": 60, "observe": True}, ctx=ToolInvocationContext(user_id=user, session_id="chat"))


def item(key, version="1"):
    return {"key": key, "version": version, "data": {"condition": "needs investigation", "detail": key}, "references": []}


@pytest.mark.asyncio
async def test_source_changes_reach_ambient_in_batches_and_not_again_after_restart(tmp_path, monkeypatch):
    from config import config
    monkeypatch.setattr(config.ambient, "event_batch_size", 2)
    tasks, runtime, conversation, manager, ambient, source, kernel, server = host_at(tmp_path)
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Maintain reliability"))
        created = await schedule(conversation)
        assert created["ok"]
        snapshot = await conversation.capability_service.build_capability_snapshot(run_context=ToolInvocationContext(user_id="alice"))
        assert next(row for row in snapshot["compact_index"] if row["name"] == "example.changes")["observation_source"] is True
        source.items = [item("first"), item("second"), item("third")]
        await kernel._cron.run_due_jobs_internal(now_ts=time.time() + 65)
        events = server.event_emitter.event_log.query(user_id="alice", event_type=EventType.ENVIRONMENT_STATE_CHANGED.value)
        assert len(events) == 3
        assert conversation.conversation_core.requests == []  # Observation alone never calls a model.
        await drain(runtime)
        task = tasks.execution_tasks(run_type="ambient")[0]
        assert len(task["runs"][0]["metadata"]["events"]) == 2
        first_context = str(conversation.conversation_core.requests[0])
        assert "first" in first_context and "second" in first_context
        scene = ambient.store.get("alice")
        assert scene.event_cursor == events[1]["seq"]
        scene.next_check_at = 0
        ambient.store.put(scene)
        await drain(runtime)
        task = tasks.get_task(task["task_id"], user_id="alice")
        assert task["runs"][1]["metadata"]["events"][0]["event_id"] == events[2]["event_id"]
        assert ambient.store.get("alice").event_cursor >= events[2]["seq"]
        restored = TemporalSchedulerService(workspace_root=str(tmp_path))
        restored.configure_tool_runtime(executor=conversation.capability_service._execute_managed_tool,
            confirmation_resolver=conversation.capability_service.requires_confirmation,
            observation_validator=conversation.capability_service.validate_observation_source, event_emitter=server.event_emitter)
        await restored.run_due_jobs_internal(now_ts=time.time() + 130)
        assert len(server.event_emitter.event_log.query(event_type=EventType.ENVIRONMENT_STATE_CHANGED.value)) == 3
        read = RuntimeReadEventTool(gateway_server=server)
        value = await read.invoke({"event_id": events[0]["event_id"]}, ToolInvocationContext(user_id="alice"))
        assert "first" in value["content"]
        with pytest.raises(FileNotFoundError):
            await read.invoke({"event_id": events[0]["event_id"]}, ToolInvocationContext(user_id="bob"))
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_publish_before_ack_crash_replays_one_fact_without_requery(tmp_path, monkeypatch):
    _, runtime, conversation, _, _, source, kernel, server = host_at(tmp_path)
    try:
        await schedule(conversation)
        source.items = [item("stable")]
        original = kernel._cron._save_jobs
        crashed = False

        def fail_ack(jobs):
            nonlocal crashed
            if not crashed and server.event_emitter.event_log.query(event_type=EventType.ENVIRONMENT_STATE_CHANGED.value):
                crashed = True
                raise OSError("simulated exit after event fsync, before source acknowledgement")
            return original(jobs)

        monkeypatch.setattr(kernel._cron, "_save_jobs", fail_ack)
        result = await kernel._cron.run_due_jobs_internal(now_ts=time.time() + 65)
        assert not result["ran"][0]["ok"] and source.calls == 1
        restored = TemporalSchedulerService(workspace_root=str(tmp_path))
        restored.configure_tool_runtime(executor=conversation.capability_service._execute_managed_tool,
            confirmation_resolver=conversation.capability_service.requires_confirmation,
            observation_validator=conversation.capability_service.validate_observation_source, event_emitter=server.event_emitter)
        await restored.run_due_jobs_internal(now_ts=time.time() + 65)
        assert source.calls == 1
        assert len(server.event_emitter.event_log.query(event_type=EventType.ENVIRONMENT_STATE_CHANGED.value)) == 1
        assert not restored._load_jobs()[0]["pending_observations"]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_sources_cannot_spoof_owner_or_escalate_to_commands(tmp_path):
    _, runtime, conversation, _, _, source, kernel, server = host_at(tmp_path)
    try:
        source.side_effect_level = "workspace_write"
        conversation.capability_service.register_tool(source)
        with pytest.raises(PermissionError):
            await schedule(conversation)
        assert not kernel._cron._load_jobs()
        source.side_effect_level = "read_only"
        conversation.capability_service.register_tool(source)
        await schedule(conversation)
        source.items = [{**item("bad"), "user_id": "bob"}]
        outcome = await kernel._cron.run_due_jobs_internal(now_ts=time.time() + 65)
        assert not outcome["ran"][0]["ok"]
        assert not server.event_emitter.event_log.query(event_type=EventType.ENVIRONMENT_STATE_CHANGED.value)
        assert not kernel._cron._load_jobs()[0].get("observation_cursor")
    finally:
        await runtime.shutdown()


def test_idempotency_key_never_rewrites_or_borrows_another_users_fact(tmp_path):
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    first = log.append(event_type="environment.state.changed", payload={"user_id": "alice", "data": 1}, idempotency_key="source-key")
    assert log.append(event_type="environment.state.changed", payload={"user_id": "alice", "data": 1}, idempotency_key="source-key") == first
    with pytest.raises(ValueError):
        log.append(event_type="environment.state.changed", payload={"user_id": "alice", "data": 2}, idempotency_key="source-key")
    other = log.append(event_type="environment.state.changed", payload={"user_id": "bob", "data": 2}, idempotency_key="source-key")
    assert other["event_id"] != first["event_id"]


@pytest.mark.asyncio
async def test_background_execution_records_real_moirai_episode_not_user_memory(tmp_path, monkeypatch):
    from config import config
    from agentkit.tools.moirai.learning import MoiraiLearning
    from tests.test_ambient_service import call
    monkeypatch.setattr(config.moirai_learning, "distillation_enabled", False)
    _, runtime, conversation, manager, ambient, source, _, _ = host_at(tmp_path, Core(call("example.changes")))
    learning = MoiraiLearning(tmp_path / "learning")
    conversation.reasoning_service = SimpleNamespace(template_memory=SimpleNamespace(learning=learning,
        record_action_success=lambda **kwargs: pytest.fail("runtime evidence must not become a fabricated user template")))
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Maintain reliability"))
        await drain(runtime)
        saved = learning.episodes("alice")
        assert len(saved) == 1 and saved[0]["execution_context"]["origin"] == "ambient"
        assert saved[0]["goal"] == "Maintain reliability"
        assert saved[0]["attempts"][0]["tool"] == "example.changes"
        assert saved[0]["goal_verification"] == "unknown"
        assert manager.get_messages("chat", user_id="alice") == []
        assert learning.episodes("bob") == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_failed_activation_does_not_acknowledge_observation_batch(tmp_path):
    _, runtime, conversation, _, ambient, source, kernel, _ = host_at(tmp_path)
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True))
        await schedule(conversation)
        source.items = [item("must-remain")]
        await kernel._cron.run_due_jobs_internal(now_ts=time.time() + 65)
        original = ambient.store.get("alice").event_cursor
        async def fail(**kwargs):
            return {"status": "success", "content": "Stopped", "execution_outcome": {"stop_reason": "budget_exhausted", "goal_status": "unverified", "response_source": "model"}}
        conversation.run_ambient_turn = fail
        await drain(runtime)
        assert ambient.store.get("alice").event_cursor == original
        assert ambient._pending_events(ambient.store.get("alice"))[0]
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_experience_write_failure_resumes_completed_result_without_reexecuting(tmp_path, monkeypatch):
    from config import config
    from agentkit.tools.moirai.learning import MoiraiLearning
    from tests.test_ambient_service import call
    monkeypatch.setattr(config.moirai_learning, "distillation_enabled", False)
    tasks, runtime, conversation, _, ambient, source, _, _ = host_at(tmp_path, Core(call("example.changes")))
    learning = MoiraiLearning(tmp_path / "learning")
    conversation.reasoning_service = SimpleNamespace(template_memory=SimpleNamespace(learning=learning))
    record = learning.record
    monkeypatch.setattr(learning, "record", lambda **kwargs: (_ for _ in ()).throw(OSError("simulated full disk")))
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Maintain reliability"))
        await drain(runtime)
        task = tasks.execution_tasks(run_type="ambient")[0]
        assert task["status"] == "paused" and source.calls == 1
        calls = len(conversation.conversation_core.requests)
        monkeypatch.setattr(learning, "record", record)
        runtime.resume_task(task_id=task["task_id"], user_id="alice")
        await drain(runtime)
        assert source.calls == 1 and len(conversation.conversation_core.requests) == calls
        assert len(learning.episodes("alice")) == 1
        assert tasks.get_task(task["task_id"], user_id="alice")["runs"][0]["status"] == "completed"
    finally:
        await runtime.shutdown()
