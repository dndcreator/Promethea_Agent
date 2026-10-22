import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import config
from gateway.agent_messages import AgentReportRequest, INBOX_RUN_TYPE, MESSAGE_PREFIX
from gateway.delegation import DelegationRequest
from gateway.background_agents import AgentControlRequest
from gateway.delegation import DelegationScope, _Budget, bind_delegation
from gateway.http.message_manager import MessageManager
from gateway.http.session_store import SessionStorage
from gateway.tools.policy import ToolPolicy
from gateway.tools.spec import SideEffectLevel, ToolSpec
from tests.test_background_agents import drain, host, parent, start


def attach_session(tmp_path, conversation):
    manager = MessageManager.__new__(MessageManager)
    manager.session_store = SessionStorage(str(tmp_path / "sessions.json"))
    manager.session = manager.session_store.load_all()
    manager.max_messages_per_session = 20
    manager.max_history_rounds = 10
    manager.memory_adapter = None
    if not manager.get_session("chat", user_id="alice"):
        manager.create_session("chat", user_id="alice")
    conversation.message_manager = manager
    return manager


def inbox_host(tmp_path, core=None):
    tasks, runtime, conversation, background = host(tmp_path, core)
    runtime.register_driver(INBOX_RUN_TYPE, background)
    manager = attach_session(tmp_path, conversation)
    return tasks, runtime, conversation, background, manager


class AnswerCore:
    def __init__(self):
        self.requests = []

    async def call_llm(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        return {"status": "success", "content": json.dumps({"action": "answer", "content": "The research is complete."})}


@pytest.mark.asyncio
async def test_settlement_wakes_idle_parent_once_and_never_becomes_user_memory(tmp_path):
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    manager.memory_adapter = Mock()
    manager.memory_adapter.is_enabled.return_value = True
    conversation._record_action_episode = Mock(side_effect=AssertionError("notification is not user experience"))

    async def child(**kwargs):
        return {"status": "success", "content": "verified child result"}

    conversation.run_delegated_turn = child
    accepted = await start(conversation, background, tools=[])
    try:
        await drain(runtime)
        assert len(core.requests) == 1
        reports = [row for row in core.requests[0] if row["content"].startswith(MESSAGE_PREFIX)]
        payload = json.loads(reports[0]["content"][len(MESSAGE_PREFIX):])
        assert payload[0]["kind"] == "subagent-settled"
        assert payload[0]["sender_task_id"] == accepted["child_id"]
        assert payload[0]["outcome"] == "completed"
        assert payload[0]["content"] == "verified child result"
        assert reports[0]["role"] == "user"  # relayed data, never system authority
        assert [row["role"] for row in manager.get_messages("chat", user_id="alice")] == ["assistant"]
        assert manager.memory_adapter.method_calls == []
        assert background.messages.pending(user_id="alice", session_id="chat") == []
        await drain(runtime)
        assert len(core.requests) == 1
        assert len(tasks.execution_tasks(run_type=INBOX_RUN_TYPE)) == 1
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_reports_are_live_authorized_quiet_or_waking_and_durable(tmp_path):
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, AnswerCore())
    entered, release = asyncio.Event(), asyncio.Event()
    accepted_reports = []

    async def child(**kwargs):
        context = kwargs["run_context"]
        accepted_reports.append(background.messages.report(AgentReportRequest(content="interim", delivery="quiet"), sender=context))
        entered.set()
        await release.wait()
        return {"status": "success", "content": "final"}

    conversation.run_delegated_turn = child
    await start(conversation, background)
    await entered.wait()
    try:
        background.recover()
        assert tasks.execution_tasks(run_type=INBOX_RUN_TYPE) == []
        rows = background.messages.pending(user_id="alice", session_id="chat")
        assert rows[0]["message_id"] == accepted_reports[0]["message_id"]
        assert rows[0]["kind"] == "subagent-report"
        context = parent()
        projected = background.messages.project(context, [])
        assert "interim" in projected[-1]["content"]
        assert background.messages.pending(user_id="bob", session_id="chat") == []
        assert background.messages.pending(user_id="alice", session_id="other") == []
        with pytest.raises(PermissionError):
            background.messages.report(AgentReportRequest(content="forged"), sender=context)
        release.set()
        await drain(runtime)
        assert len(conversation.conversation_core.requests) == 1  # quiet + settlement coalesce
        assert background.messages.pending(user_id="alice", session_id="chat") == []
    finally:
        release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_waking_report_can_reach_parent_before_child_finishes(tmp_path):
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    entered, release = asyncio.Event(), asyncio.Event()

    async def child(**kwargs):
        background.messages.report(AgentReportRequest(content="please review", delivery="wakeup"), sender=kwargs["run_context"])
        entered.set()
        await release.wait()
        return {"status": "success", "content": "final"}

    conversation.run_delegated_turn = child
    await start(conversation, background)
    await entered.wait()
    try:
        await runtime._recover_available()
        delivery = next(row for row in runtime.active_run_ids() if row.startswith("agent_delivery_"))
        await runtime._jobs[delivery]
        background.recover()
        assert len(core.requests) == 1
        assert background.messages.pending(user_id="alice", session_id="chat") == []
        release.set()
        await drain(runtime)
        assert len(core.requests) == 2
    finally:
        release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_active_user_turn_receives_batch_without_spawning_competing_turn(tmp_path):
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    conversation.run_delegated_turn = lambda **kwargs: asyncio.sleep(0, result={"status": "success", "content": "child result"})
    assert manager.begin_turn("chat", "user-turn", "user", "research", "alice")
    await start(conversation, background)
    try:
        await drain(runtime)
        assert core.requests == []
        context = parent()
        result = await conversation.run_chat_loop([{"role": "user", "content": "research"}], user_id="alice", session_id="chat", run_context=context, user_config=config.model_dump())
        assert result["agent_message_ids"]
        assert background.messages.pending(user_id="alice", session_id="chat")
        assert manager.commit_turn("chat", "user-turn", result["content"], "alice", agent_message_ids=result["agent_message_ids"])
        await drain(runtime)
        assert len(core.requests) == 1
        assert tasks.execution_tasks(run_type=INBOX_RUN_TYPE) == []
        assert background.messages.pending(user_id="alice", session_id="chat") == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_settlement_and_receipt_recovery_after_process_restart(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    conversation.run_delegated_turn = lambda **kwargs: asyncio.sleep(0, result={"status": "success", "content": "durable result"})
    await start(conversation, background)
    await drain(runtime)
    await runtime.shutdown()
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    try:
        await runtime.recover_incomplete()
        await drain(runtime)
        assert len(core.requests) == 1
        # Rebuild a lost outbox acknowledgement from the committed Session receipt.
        for task in tasks.execution_tasks(run_type="subagent"):
            for run in task["runs"]:
                for row in tasks._tasks[task["task_id"]]["runs"][0]["metadata"]["agent_outbox"]:
                    row["received"] = False
        tasks._persist()
    finally:
        await runtime.shutdown()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    try:
        await runtime.recover_incomplete()
        await drain(runtime)
        assert len(core.requests) == 1
        assert background.messages.pending(user_id="alice", session_id="chat") == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_no_wakeup_during_shutdown_disabled_or_paused_parent(tmp_path, monkeypatch):
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, AnswerCore())
    conversation.run_delegated_turn = lambda **kwargs: asyncio.sleep(0, result={"status": "success", "content": "done"})
    await start(conversation, background)
    # Keep the real conversation busy until shutdown has parked durable work.
    manager.begin_turn("chat", "busy", "user", "work", "alice")
    await drain(runtime)
    monkeypatch.setattr(config.multi_agent, "enabled", False)
    manager.abort_turn("chat", "busy", "alice")
    await runtime._recover_available()
    assert conversation.conversation_core.requests == []
    assert background.messages.pending(user_id="alice", session_id="chat")
    await runtime.shutdown()


def test_outbox_write_and_ack_rollback_on_disk_failure(tmp_path, monkeypatch):
    tasks, runtime, conversation, background = host(tmp_path)
    task = tasks.create_task(user_id="alice", title="test", initial_run={"run_id": "one", "run_type": "subagent"})
    entry = {"message_id": "message", "received": False}
    persist = tasks._persist
    monkeypatch.setattr(tasks, "_persist", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        tasks.append_agent_message(task_id=task["task_id"], user_id="alice", run_id="one", message=entry)
    assert "agent_outbox" not in tasks.get_task(task["task_id"], user_id="alice")["runs"][0]["metadata"]
    monkeypatch.setattr(tasks, "_persist", persist)
    tasks.append_agent_message(task_id=task["task_id"], user_id="alice", run_id="one", message=entry)
    monkeypatch.setattr(tasks, "_persist", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        tasks.acknowledge_agent_messages(user_id="alice", message_ids=["message"])
    assert not tasks.get_task(task["task_id"], user_id="alice")["runs"][0]["metadata"]["agent_outbox"][0]["received"]


def test_runtime_turn_commit_is_atomic_and_not_synthetic_user_input(tmp_path, monkeypatch):
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path)
    manager.begin_turn("chat", "notification", "runtime", "", "alice")
    save = manager.session_store.save_all
    monkeypatch.setattr(manager.session_store, "save_all", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        manager.commit_turn("chat", "notification", "summary", "alice", agent_message_ids=["one"])
    assert manager.get_messages("chat", user_id="alice") == []
    assert manager.agent_message_receipts("chat", user_id="alice") == set()
    assert manager.has_active_turn("chat", user_id="alice")
    monkeypatch.setattr(manager.session_store, "save_all", save)
    assert manager.commit_turn("chat", "notification", "summary", "alice", agent_message_ids=["one"])
    assert manager.agent_message_receipts("chat", user_id="alice") == {"one"}


def test_background_notice_cannot_grant_confirmation():
    scope = DelegationScope(_Budget(), background_notification=True)
    spec = ToolSpec(tool_name="write", service_name="test", description="external write", side_effect_level=SideEffectLevel.EXTERNAL_WRITE)
    with bind_delegation(scope):
        decision = ToolPolicy().evaluate(spec=spec, run_context=parent(), user_config={})
    assert not decision.allowed


@pytest.mark.asyncio
async def test_report_cannot_forge_sender_or_survive_its_execution(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    saved = []

    async def child(**kwargs):
        context = kwargs["run_context"]
        saved.append((context, deepcopy(runtime._tokens[context.task_run_id])))
        forged = context.model_copy(update={"task_id": "sibling"})
        with pytest.raises(PermissionError):
            background.messages.report(AgentReportRequest(content="forged"), sender=forged)
        return {"status": "success", "content": "done"}

    conversation.run_delegated_turn = child
    accepted = await start(conversation, background)
    await drain(runtime)
    context, token = saved[0]
    scope = DelegationScope(_Budget(), depth=1, agent_task_id=accepted["child_id"])
    try:
        with bind_delegation(scope), pytest.raises(PermissionError):
            background.messages.report(AgentReportRequest(content="stale"), sender=context)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_same_agent_turns_serialize_but_distinct_children_can_run(tmp_path):
    tasks, runtime, conversation, background = host(tmp_path)
    async with conversation.agent_execution("alice", "chat"):
        entered = asyncio.Event()

        async def other_turn():
            async with conversation.agent_execution("alice", "chat"):
                entered.set()

        job = asyncio.create_task(other_turn())
        await asyncio.sleep(0)
        assert not entered.is_set()
        async with conversation.agent_execution("alice", "chat", "child"):
            assert conversation.agent_is_active("alice", "chat", "child")
    await job
    assert entered.is_set()
    assert not conversation._active_agent_turns


@pytest.mark.asyncio
async def test_nested_settlement_only_wakes_direct_parent_and_respects_pause(tmp_path, monkeypatch):
    monkeypatch.setattr(config.multi_agent, "max_depth", 3)
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    manager.begin_turn("chat", "user-busy", "user", "research", "alice")
    release, entered = asyncio.Event(), asyncio.Event()
    nested = []
    original = conversation.run_delegated_turn

    async def child(**kwargs):
        if kwargs["objective"] == "independent objective":
            nested.append(await background.start(DelegationRequest(label="nested", objective="nested work", tools=[]), parent=kwargs["run_context"], user_config=config.model_dump()))
            return {"status": "success", "content": "dispatched nested work"}
        if kwargs["objective"] == "nested work":
            entered.set()
            await release.wait()
            return {"status": "success", "content": "nested result"}
        return await original(**kwargs)

    conversation.run_delegated_turn = child
    accepted = await start(conversation, background)
    await entered.wait()
    # Wait for the direct parent message to finish, without waiting for its child.
    await runtime._jobs[accepted["run_id"]]
    runtime.pause_task(task_id=accepted["child_id"], user_id="alice")
    release.set()
    try:
        await drain(runtime)
        assert not core.requests
        root_rows = background.messages.pending(user_id="alice", session_id="chat")
        assert all(row["sender_task_id"] == accepted["child_id"] for row in root_rows)
        rows = background.messages.pending(user_id="alice", session_id="chat", agent_task_id=accepted["child_id"])
        assert rows[0]["sender_task_id"] == nested[0]["child_id"]
        runtime.resume_task(task_id=accepted["child_id"], user_id="alice")
        await drain(runtime)
        assert len(core.requests) == 1
        assert "nested result" in json.dumps(core.requests)
        assert background.messages.pending(user_id="alice", session_id="chat", agent_task_id=accepted["child_id"]) == []
        assert len(tasks.get_task(accepted["child_id"], user_id="alice")["runs"]) == 2
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_checkpointed_parent_result_resumes_without_repeating_model_or_commit(tmp_path, monkeypatch):
    core = AnswerCore()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    conversation.run_delegated_turn = lambda **kwargs: asyncio.sleep(0, result={"status": "success", "content": "child"})
    monkeypatch.setattr(manager, "commit_turn", Mock(side_effect=OSError("disk full")))
    await start(conversation, background)
    await drain(runtime)
    delivery = tasks.execution_tasks(run_type=INBOX_RUN_TYPE)[0]
    assert delivery["status"] == "paused"
    assert len(core.requests) == 1
    assert manager.get_messages("chat", user_id="alice") == []
    await runtime.shutdown()
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, core)
    try:
        runtime.resume_task(task_id=delivery["task_id"], user_id="alice")
        await drain(runtime)
        assert len(core.requests) == 1
        assert len(manager.get_messages("chat", user_id="alice")) == 1
        assert background.messages.pending(user_id="alice", session_id="chat") == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_fifo_batch_has_one_runtime_settlement_not_one_per_internal_turn(tmp_path):
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path, AnswerCore())
    manager.begin_turn("chat", "busy", "user", "research", "alice")
    entered, release = asyncio.Event(), asyncio.Event()

    async def child(**kwargs):
        if kwargs["objective"] == "independent objective":
            entered.set()
            await release.wait()
        return {"status": "success", "content": kwargs["objective"]}

    conversation.run_delegated_turn = child
    accepted = await start(conversation, background)
    await entered.wait()
    await background.control(AgentControlRequest(action="send", child_id=accepted["child_id"], message="follow-up"), parent=parent(), user_config=config.model_dump())
    release.set()
    try:
        await drain(runtime)
        rows = background.messages.pending(user_id="alice", session_id="chat")
        assert len(rows) == 1
        assert rows[0]["content"] == "follow-up"
        assert rows[0]["outcome"] == "completed"
    finally:
        await runtime.shutdown()


def test_personal_space_transfer_keeps_conversation_delivery_receipts(tmp_path):
    tasks, runtime, conversation, background, manager = inbox_host(tmp_path)
    manager.begin_turn("chat", "notification", "runtime", "", "alice")
    manager.commit_turn("chat", "notification", "reply", "alice", agent_message_ids=["one"])
    exported = manager.export_user_sessions(user_id="alice")
    manager.replace_user_sessions(user_id="alice", sessions=exported)
    assert manager.agent_message_receipts("chat", user_id="alice") == {"one"}
    assert manager.begin_turn("chat", "notification", "runtime", "", "alice")
    assert manager.commit_turn("chat", "notification", "must not duplicate", "alice")
    assert len(manager.get_messages("chat", user_id="alice")) == 1

