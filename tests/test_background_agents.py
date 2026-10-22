import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import config
from gateway.background_agents import AgentControlRequest, BackgroundAgents
from gateway.capability_service import CapabilityService
from gateway.conversation_service import ConversationService
from gateway.delegation import DelegationRequest, DelegationScope, _Budget, bind_delegation
from gateway.models.run_context import RunContext
from gateway.models.session_state import SessionState
from gateway.task_runtime import TaskRuntime
from gateway.task_service import TaskService
from gateway.workflow_engine import WorkflowEngine


def parent(user="alice", session="chat"):
    return RunContext(
        request_id="request", trace_id="trace", action_loop_id="parent-action",
        input_payload={"metadata": {"multi_agent": True, "ui_language": "zh"}},
        session_state=SessionState(session_id=session, user_id=user, trace_id="trace"),
    )


def host(tmp_path, core=None):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflow = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks)
    runtime = TaskRuntime(task_service=tasks, workflow_engine=workflow)
    capability = CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}))
    capability._tool_discovery_initialized = True
    conversation = ConversationService(conversation_core=core or SimpleNamespace(), capability_service=capability)
    conversation.action_service.task_service = tasks
    conversation._get_user_prompt_and_config = AsyncMock(return_value=("Core identity", config.model_dump()))
    background = BackgroundAgents(conversation=conversation, task_runtime=runtime, task_service=tasks)
    conversation.background_agents = background
    runtime.register_driver("subagent", background)
    return tasks, runtime, conversation, background


async def drain(runtime):
    for _ in range(100):
        jobs = list(runtime._jobs.values())
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
            await asyncio.sleep(0)
        await runtime._recover_available()
        if not runtime.active_run_ids():
            return
    raise AssertionError("background work did not quiesce")


async def start(conversation, background, **kwargs):
    with conversation.delegation.turn():
        return await background.start(DelegationRequest(label="Research", objective="independent objective", **kwargs), parent=parent(), user_config=config.model_dump())


@pytest.mark.asyncio
async def test_background_survives_parent_scope_and_orders_followups(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    inputs = []

    async def run(**kwargs):
        inputs.append((kwargs["objective"], deepcopy(kwargs["history"])))
        if len(inputs) == 1:
            entered.set()
            await release.wait()
        return {"status": "success", "content": f"result-{len(inputs)}"}

    conversation.run_delegated_turn = run
    accepted = await start(conversation, background)
    await entered.wait()
    assert tasks.get_task(accepted["child_id"], user_id="alice")["status"] == "running"
    await background.control(AgentControlRequest(action="send", child_id=accepted["child_id"], message="follow-up"), parent=parent(), user_config=config.model_dump())
    assert len(inputs) == 1
    release.set()
    try:
        await drain(runtime)
        task = tasks.get_task(accepted["child_id"], user_id="alice")
        assert task["status"] == "waiting_user"
        assert [row[0] for row in inputs] == ["independent objective", "follow-up"]
        assert inputs[1][1][-1] == {"role": "assistant", "content": "result-1"}
        assert [row["status"] for row in task["runs"]] == ["completed", "completed"]
        assert background.messages.pending(user_id="alice", session_id="chat")[-1]["content"] == "result-2"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_cold_restart_uses_same_child_and_replays_completed_result_without_model(tmp_path):
    class Core:
        calls = 0

        async def call_llm(self, messages, **kwargs):
            self.calls += 1
            return {"status": "success", "content": '{"action":"answer","content":"persistent result"}'}

    core = Core()
    tasks, runtime, conversation, background = host(tmp_path, core)
    accepted = await start(conversation, background, tools=[])
    await drain(runtime)
    task = tasks.get_task(accepted["child_id"], user_id="alice")
    assert task["runs"][0]["metadata"]["checkpoint"]["result"]["content"] == "persistent result"
    # Simulate death between durable Action completion and Task run settlement.
    tasks.update_run(task_id=task["task_id"], user_id="alice", run_id=accepted["run_id"], status="running")
    await runtime.shutdown()
    restored, restarted, next_conversation, next_background = host(tmp_path, core)
    try:
        await restarted.recover_incomplete()
        await drain(restarted)
        row = restored.get_task(accepted["child_id"], user_id="alice")
        assert core.calls == 1
        assert row["status"] == "waiting_user" and len(row["runs"]) == 1
        assert next_background.view(row)["turns"][0]["output"] == "persistent result"
        assert row["runs"][0]["attempts"][-1]["epoch"] > row["runs"][0]["attempts"][0]["epoch"]
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_shutdown_during_tool_does_not_replay_side_effect_on_restart(tmp_path):
    entered = asyncio.Event()
    invocations = []
    recovery_seen = []

    class Core:
        async def call_llm(self, messages, **kwargs):
            if not isinstance(messages[-1]["content"], list):
                return {"status": "success", "content": '{"action":"tool_call","tool_name":"test.write","args":{}}'}
            observation = json.loads(messages[-1]["content"][0]["text"])
            recovery_seen.append(observation)
            return {"status": "success", "content": json.dumps({"action": "answer", "content": "check actual file state before continuing", "evidence_refs": [observation["observation_id"]]})}

    tasks, runtime, conversation, background = host(tmp_path, Core())

    async def write(*args):
        invocations.append("effect dispatched")
        entered.set()
        await asyncio.Future()

    tool = SimpleNamespace(tool_id="test.write", name="test.write", description="workspace write", side_effect_level="workspace_write", invoke=write, input_schema={"type": "object"})
    conversation.capability_service.register_tool(tool)
    accepted = await start(conversation, background)
    await entered.wait()
    await runtime.shutdown()
    restored, restarted, next_conversation, next_background = host(tmp_path, Core())
    next_conversation.capability_service.register_tool(tool)
    try:
        await restarted.recover_incomplete()
        await drain(restarted)
        task = restored.get_task(accepted["child_id"], user_id="alice")
        assert invocations == ["effect dispatched"]
        assert task["status"] == "waiting_user"
        assert recovery_seen[0]["error"]["code"] == "TOOL_OUTCOME_UNKNOWN"
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_parent_and_owner_authority_cannot_be_forged(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "result"})
    accepted = await start(conversation, background)
    try:
        await drain(runtime)
        request = AgentControlRequest(action="get", child_id=accepted["child_id"])
        with pytest.raises(KeyError):
            await background.control(request, parent=parent(user="bob"), user_config={})
        with pytest.raises(PermissionError):
            await background.control(request, parent=parent(session="other-chat"), user_config={})
        with bind_delegation(DelegationScope(_Budget(), depth=1, agent_task_id="sibling")):
            with pytest.raises(PermissionError):
                await background.control(request, parent=parent(), user_config={})
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_pause_resume_cancel_and_disabled_recovery(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    entered = asyncio.Event()

    async def run(**kwargs):
        entered.set()
        await asyncio.Future()

    conversation.run_delegated_turn = run
    accepted = await start(conversation, background)
    await entered.wait()
    runtime.pause_task(task_id=accepted["child_id"], user_id="alice")
    await asyncio.gather(*list(runtime._jobs.values()), return_exceptions=True)
    await asyncio.sleep(0)
    assert tasks.get_task(accepted["child_id"], user_id="alice")["status"] == "paused"
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "resumed"})
    monkeypatch.setattr(config.multi_agent, "enabled", False)
    runtime.resume_task(task_id=accepted["child_id"], user_id="alice")
    await runtime._recover_available()
    assert runtime.active_run_ids() == []
    monkeypatch.setattr(config.multi_agent, "enabled", True)
    await drain(runtime)
    assert tasks.get_task(accepted["child_id"], user_id="alice")["status"] == "waiting_user"
    runtime.pause_task(task_id=accepted["child_id"], user_id="alice")
    assert runtime.resume_task(task_id=accepted["child_id"], user_id="alice")["status"] == "waiting_user"
    runtime.cancel_task(task_id=accepted["child_id"], user_id="alice")
    with pytest.raises(ValueError):
        await background.control(AgentControlRequest(action="send", child_id=accepted["child_id"], message="more"), parent=parent(), user_config=config.model_dump())
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_initial_acceptance_is_atomic_and_does_not_persist_secrets(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    persist = tasks._persist
    monkeypatch.setattr(tasks, "_persist", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        await start(conversation, background)
    assert tasks.list_tasks(user_id="alice") == [] and runtime.active_run_ids() == []
    monkeypatch.setattr(tasks, "_persist", persist)
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "result"})
    with conversation.delegation.turn():
        await background.start(DelegationRequest(label="work", objective="inspect"), parent=parent(), user_config={"api": {"api_key": "never-store-this-credential"}})
    try:
        await drain(runtime)
        assert "never-store-this-credential" not in tasks.storage_path.read_text(encoding="utf-8")
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_accepted_inbox_survives_dispatch_failure_and_is_recoverable(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "done"})
    schedule = runtime.schedule_run
    monkeypatch.setattr(runtime, "schedule_run", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("host stopping")))
    accepted = await start(conversation, background)
    assert accepted["status"] == "accepted"
    assert tasks.get_task(accepted["child_id"], user_id="alice")["runs"][0]["status"] == "pending"
    monkeypatch.setattr(runtime, "schedule_run", schedule)
    try:
        await drain(runtime)
        assert tasks.get_task(accepted["child_id"], user_id="alice")["runs"][0]["status"] == "completed"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_background_pending_admission_is_bounded(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    monkeypatch.setattr(config.multi_agent, "max_pending", 1)
    monkeypatch.setattr(background, "available", lambda task: False)
    accepted = await start(conversation, background)
    with pytest.raises(PermissionError, match="admission"):
        await start(conversation, background)
    assert len(tasks.list_tasks(user_id="alice")) == 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_foreground_and_background_share_the_same_capacity_ceiling(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    entered = asyncio.Event()
    monkeypatch.setattr(config.multi_agent, "max_parallel", 1)

    async def run(**kwargs):
        entered.set()
        await asyncio.Future()

    conversation.run_delegated_turn = run
    await start(conversation, background)
    await entered.wait()
    try:
        with conversation.delegation.turn():
            with pytest.raises(PermissionError, match="capacity"):
                await conversation.delegation.delegate(conversation, DelegationRequest(label="foreground", objective="must wait", run_in_background=False), parent=parent(), user_config={})
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_corrupt_descriptor_cannot_reset_delegation_depth(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    conversation.run_delegated_turn = AsyncMock()
    original = background.available
    background.available = lambda task: False
    accepted = await start(conversation, background)
    payload = tasks.export_user_state(user_id="alice")
    payload["tasks"][accepted["child_id"]]["metadata"]["delegation"]["depth"] = 0
    tasks.import_user_state(user_id="alice", payload=payload, merge=False)
    background.available = original
    try:
        await drain(runtime)
        assert tasks.get_task(accepted["child_id"], user_id="alice")["status"] == "failed"
        conversation.run_delegated_turn.assert_not_awaited()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_failed_followup_and_lease_writes_roll_back_in_memory(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    conversation.run_delegated_turn = AsyncMock(return_value={"status": "success", "content": "done"})
    background.available = lambda task: False
    accepted = await start(conversation, background)
    before = tasks.get_task(accepted["child_id"], user_id="alice")
    persist = tasks._persist
    monkeypatch.setattr(tasks, "_persist", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        await background.control(AgentControlRequest(action="send", child_id=accepted["child_id"], message="must not execute"), parent=parent(), user_config=config.model_dump())
    assert tasks.get_task(accepted["child_id"], user_id="alice") == before
    with pytest.raises(OSError):
        tasks.claim_execution(task_id=accepted["child_id"], user_id="alice", run_id=accepted["run_id"], owner_id="test")
    assert tasks.get_task(accepted["child_id"], user_id="alice") == before
    monkeypatch.setattr(tasks, "_persist", persist)
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_stale_driver_cannot_pause_or_complete_a_new_execution_owner(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(**kwargs):
        entered.set()
        await release.wait()
        return {"status": "success", "content": "stale result"}

    conversation.run_delegated_turn = run
    accepted = await start(conversation, background)
    await entered.wait()
    tasks.interrupt_owned_executions(owner_id=runtime.runtime_id)
    token = tasks.claim_execution(task_id=accepted["child_id"], user_id="alice", run_id=accepted["run_id"], owner_id="new-runtime")
    release.set()
    await asyncio.gather(*list(runtime._jobs.values()), return_exceptions=True)
    task = tasks.get_task(accepted["child_id"], user_id="alice")
    assert task["runs"][0]["status"] == "running"
    assert "output" not in task["runs"][0]["metadata"]
    tasks.assert_execution(task_id=accepted["child_id"], user_id="alice", token=token)
    await runtime.shutdown()
