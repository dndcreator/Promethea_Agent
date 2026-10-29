from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.checkpoint import capture, restore
from gateway.action.model_action import AnswerDeltaProjector, InvalidModelAction, parse_model_action
from gateway.action.models import ActionContext, ActionRun
from gateway.conversation_service import ConversationService
from gateway.http.message_manager import MessageManager
from gateway.http.session_store import SessionStorage


def manager_at(path):
    manager = MessageManager.__new__(MessageManager)
    manager.session_store = SessionStorage(str(path))
    manager.session = manager.session_store.load_all()
    manager.memory_adapter = None
    manager.max_messages_per_session = 100
    return manager


def make_turn(tmp_path):
    manager = manager_at(tmp_path / "sessions.json")
    manager.create_session("s1", user_id="u1")
    manager.begin_turn("s1", "t1", "user", "original", user_id="u1")
    return manager


def conversation_for(manager, actions):
    service = ConversationService.__new__(ConversationService)
    service.message_manager = manager
    service.action_service = actions
    return service


class ControlledCore:
    def __init__(self, first):
        self.first = first
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def call_llm(self, messages, **kwargs):
        return {"status": "success", "content": "".join([chunk async for chunk in self.call_llm_stream(messages, **kwargs)])}

    async def call_llm_stream(self, messages, **kwargs):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            self.entered.set()
            await self.release.wait()
            yield self.first
        else:
            yield '{"action":"answer","content":"updated answer"}'


def apply_updates(updates):
    text = ""
    for update in updates:
        if isinstance(update, str):
            text += update
        elif update.get("type", "text") == "text":
            text = update["content"] if update["operation"] == "replace" else text + update["content"]
    return text


@pytest.mark.parametrize("raw", [
    '{"metadata":{"action":"answer","content":"private"},"action":"tool_call","tool_name":"x"}',
    '{"action":"tool_call","args":{"action":"answer","content":"private"}}',
    '{"args":[{"action":"answer","content":"private"}],"action":"tool_calls"}',
    'plain text {"action":"answer","content":"private"}',
])
def test_projector_never_reads_nested_action_fields(raw):
    projector = AnswerDeltaProjector()
    assert "".join(projector.feed(char) for char in raw) == ""


@pytest.mark.parametrize("raw", [
    '{"action":"answer","content":"hello \\uD83D\\uDE00\\nworld"}',
    '{"metadata":{"content":"private"},"action":" Answer ","content":"hello"}',
    '{"content":"hello","action":"answer"}',
    '{"action":"answer","answer":"hello"}',
])
def test_projector_matches_committed_answer_at_every_chunk_boundary(raw):
    expected = parse_model_action(raw).content
    for split in range(len(raw) + 1):
        projector = AnswerDeltaProjector()
        assert projector.feed(raw[:split]) + projector.feed(raw[split:]) == expected


def test_projector_emits_before_complete_json_but_waits_for_action_discriminator():
    projector = AnswerDeltaProjector()
    assert projector.feed('{"action":"answer","content":"hel') == "hel"
    assert projector.feed('lo"}') == "lo"
    projector = AnswerDeltaProjector()
    assert projector.feed('{"content":"hello",') == ""
    assert projector.feed('"action":"answer"}') == "hello"
    with pytest.raises(InvalidModelAction, match="duplicate"):
        parse_model_action('{"action":"answer","content":"draft","content":"other"}')


@pytest.mark.asyncio
async def test_invalid_stream_is_replaced_not_concatenated():
    class Core:
        calls = 0

        async def call_llm_stream(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield '{"action":"answer","content":"discarded-draft"'
                yield ' BROKEN'
            else:
                yield '{"action":"answer","content":"final-answer"}'

    updates = []

    async def publish(update):
        updates.append(update)

    result = await ActionService(conversation_core=Core()).run_action(goal="answer", messages=[], output_sink=publish)
    assert "discarded-draft" in updates
    assert {"operation": "replace", "content": ""} in updates
    assert result["content"] == apply_updates(updates) == "final-answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [
    '{"action":"answer","content":"outdated answer"}',
    '{"action":"tool_call","id":"old","tool_name":"dangerous.write","args":{}}',
])
async def test_steer_current_model_step_is_owned_idempotent_and_discards_old_action(tmp_path, first):
    manager = make_turn(tmp_path)
    core = ControlledCore(first)
    actions = ActionService(conversation_core=core)
    conversation = conversation_for(manager, actions)
    executed, updates, checkpoints = [], [], []

    async def execute(name, arguments):
        executed.append(name)

    async def publish(update):
        updates.append(update)

    task = asyncio.create_task(actions.run_action(
        goal="original", messages=[{"role": "user", "content": "original"}],
        session_id="s1", user_id="u1", run_context=SimpleNamespace(conversation_turn_id="t1"),
        tool_executor=execute, approved_call_ids={"old"}, output_sink=publish,
        checkpoint_sink=checkpoints.append, **conversation._steering_callbacks("s1", "u1", "t1"),
    ))
    await asyncio.wait_for(core.entered.wait(), 2)
    try:
        with pytest.raises(KeyError):
            await conversation.steer_turn(session_id="s1", user_id="other", turn_id="t1", message_id="m1", message="new")
        with pytest.raises(ValueError, match="turn_not_steerable"):
            await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="other", message_id="m1", message="new")
        receipt = await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="new")
        assert receipt["status"] == "queued"
        assert (await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="new"))["status"] == "queued"
        with pytest.raises(ValueError, match="steering_id_conflict"):
            await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="different")
    finally:
        core.release.set()
        result = await asyncio.wait_for(task, 3)
    assert result["status"] == "success"
    assert executed == []
    assert sum(message == {"role": "user", "content": "new"} for message in core.calls[1]) == 1
    assert result["content"] == apply_updates(updates) == "updated answer"
    assert checkpoints[-1]["applied_steering_ids"] == ["m1"]
    assert manager.turn_steering("s1", "t1", user_id="u1")[0]["status"] == "applied"
    assert actions._active_runs == {}
    manager.commit_turn("s1", "t1", result["content"], user_id="u1")
    reloaded = manager_at(tmp_path / "sessions.json")
    rows = reloaded.get_messages("s1", user_id="u1")
    assert [row["content"] for row in rows] == ["original", "new", "updated answer"]
    assert rows[1]["steering_status"] == "applied"
    assert (await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="new"))["status"] == "applied"
    with pytest.raises(ValueError, match="turn_not_steerable"):
        await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m2", message="late")


@pytest.mark.asyncio
async def test_steer_during_tool_preserves_observation_and_requires_fresh_approval(tmp_path):
    manager = make_turn(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    class Core:
        calls = []

        async def call_llm(self, messages, **kwargs):
            self.calls.append(list(messages))
            name = "read" if len(self.calls) == 1 else "write"
            return {"status": "success", "content": json.dumps({"action": "tool_call", "id": name, "tool_name": name, "args": {}})}

    core = Core()
    actions = ActionService(conversation_core=core)
    conversation = conversation_for(manager, actions)
    executed = []

    async def execute(name, arguments):
        executed.append(name)
        entered.set()
        await release.wait()
        return {"ok": True, "value": "read result"}

    task = asyncio.create_task(actions.run_action(
        goal="original", messages=[], session_id="s1", user_id="u1",
        run_context=SimpleNamespace(conversation_turn_id="t1"), tool_executor=execute,
        approved_call_ids={"write"}, confirmation_resolver=lambda name, args: name == "write",
        **conversation._steering_callbacks("s1", "u1", "t1"),
    ))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="change direction")
    finally:
        release.set()
        result = await asyncio.wait_for(task, 3)
    assert executed == ["read"]
    assert result["status"] == "needs_confirmation"
    assert result["tool_name"] == "write"
    assert result["observations"][0]["ok"] is True
    assert core.calls[1][-1] == {"role": "user", "content": "change direction"}
    assert result["applied_steering_ids"] == ["m1"]


@pytest.mark.asyncio
async def test_concurrent_retries_commit_one_instruction_and_one_receipt_event(tmp_path):
    manager = make_turn(tmp_path)
    core = ControlledCore('{"action":"answer","content":"stale"}')

    class Emitter:
        events = []

        async def emit(self, event, payload):
            self.events.append(event.value)

    emitter = Emitter()
    actions = ActionService(conversation_core=core, event_emitter=emitter)
    conversation = conversation_for(manager, actions)
    task = asyncio.create_task(actions.run_action(
        goal="g", messages=[], session_id="s1", user_id="u1",
        run_context=SimpleNamespace(conversation_turn_id="t1"),
        **conversation._steering_callbacks("s1", "u1", "t1"),
    ))
    await asyncio.wait_for(core.entered.wait(), 2)
    try:
        async with actions.control_lock:
            retries = [asyncio.create_task(conversation.steer_turn(
                session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="new",
            )) for _ in range(2)]
            await asyncio.sleep(0)
        assert [row["status"] for row in await asyncio.gather(*retries)] == ["queued", "queued"]
        assert emitter.events.count("action.steering.received") == 1
        assert len(manager.turn_steering("s1", "t1", user_id="u1")) == 1
    finally:
        core.release.set()
        await asyncio.wait_for(task, 3)


def test_unapplied_guidance_survives_abort_and_storage_failure_rolls_back(tmp_path, monkeypatch):
    manager = make_turn(tmp_path)
    original_save = manager.session_store.save_all

    def fail(_):
        raise OSError("disk unavailable")

    monkeypatch.setattr(manager.session_store, "save_all", fail)
    with pytest.raises(OSError):
        manager.add_turn_steering("s1", "t1", user_id="u1", message_id="m1", content="guidance")
    assert manager.turn_steering("s1", "t1", user_id="u1") == []
    monkeypatch.setattr(manager.session_store, "save_all", original_save)
    manager.add_turn_steering("s1", "t1", user_id="u1", message_id="m1", content="guidance")
    manager.abort_turn("s1", "t1", user_id="u1", error={"message": "cancelled"})
    rows = manager_at(tmp_path / "sessions.json").get_messages("s1", user_id="u1")
    assert rows[1]["steering_status"] == "not_applied"
    assert rows[1]["content"] == "guidance"


def test_checkpoint_preserves_applied_commands_without_persisting_draft():
    run = ActionRun(goal="g", messages=[], context=ActionContext(), applied_steering_ids=["m1"], streamed_answer="draft")
    checkpoint = capture(run, [], {})
    restored = restore(checkpoint, run.context)
    assert restored.applied_steering_ids == ["m1"]
    assert restored.streamed_answer == ""


@pytest.mark.asyncio
async def test_restored_checkpoint_reconciles_receipt_without_reinserting_user_message(tmp_path):
    manager = make_turn(tmp_path)
    manager.add_turn_steering("s1", "t1", user_id="u1", message_id="m1", content="new")
    context = ActionContext(**conversation_for(manager, None)._steering_callbacks("s1", "u1", "t1"))
    run = ActionRun(goal="g", messages=[], context=context, applied_steering_ids=["m1"])
    messages = [{"role": "user", "content": "new"}]
    assert not await ActionService(conversation_core=None)._apply_steering(run, messages, {}, None)
    assert messages == [{"role": "user", "content": "new"}]
    assert manager.turn_steering("s1", "t1", user_id="u1")[0]["status"] == "applied"


@pytest.mark.asyncio
async def test_guidance_received_during_confirmation_validation_withdraws_old_proposal(tmp_path):
    manager = make_turn(tmp_path)
    core = ControlledCore('{"action":"tool_call","id":"old","tool_name":"write","args":{}}')
    core.release.set()
    actions = ActionService(conversation_core=core)
    conversation = conversation_for(manager, actions)
    checking, proceed = asyncio.Event(), asyncio.Event()

    async def requires_confirmation(name, args):
        checking.set()
        await proceed.wait()
        return True

    task = asyncio.create_task(actions.run_action(
        goal="g", messages=[], session_id="s1", user_id="u1",
        run_context=SimpleNamespace(conversation_turn_id="t1"),
        confirmation_resolver=requires_confirmation,
        **conversation._steering_callbacks("s1", "u1", "t1"),
    ))
    await asyncio.wait_for(checking.wait(), 2)
    try:
        await conversation.steer_turn(session_id="s1", user_id="u1", turn_id="t1", message_id="m1", message="do not write")
    finally:
        proceed.set()
        result = await asyncio.wait_for(task, 3)
    assert result["status"] == "success"
    assert result["content"] == "updated answer"
    assert core.calls[1][-1] == {"role": "user", "content": "do not write"}


@pytest.mark.asyncio
async def test_confirmation_resume_preserves_applied_ids_and_replans_new_guidance(tmp_path):
    manager = make_turn(tmp_path)
    core = ControlledCore('{"action":"tool_call","id":"old","tool_name":"write","args":{}}')
    core.release.set()
    actions = ActionService(conversation_core=core)
    callbacks = conversation_for(manager, actions)._steering_callbacks("s1", "u1", "t1")
    manager.add_turn_steering("s1", "t1", user_id="u1", message_id="m0", content="initial guidance")
    pending = await actions.run_action(
        goal="g", messages=[], user_id="u1", session_id="s1",
        run_context=SimpleNamespace(conversation_turn_id="t1"), confirmation_resolver=lambda *_: True, **callbacks,
    )
    assert pending["applied_steering_ids"] == ["m0"]
    manager.add_turn_steering("s1", "t1", user_id="u1", message_id="m1", content="new guidance")
    executed = []

    async def execute(name, args):
        executed.append(name)

    result = await actions.resume_action(
        pending=pending, approved_call_id="old", user_config={}, user_id="u1", session_id="s1",
        run_context=SimpleNamespace(conversation_turn_id="t1"), tool_executor=execute,
        confirmation_resolver=lambda *_: True, **callbacks,
    )
    assert result["status"] == "success"
    assert executed == []
    assert core.calls[1].count({"role": "user", "content": "initial guidance"}) == 1
    assert core.calls[1].count({"role": "user", "content": "new guidance"}) == 1


@pytest.mark.asyncio
async def test_sse_delivers_live_draft_then_replacement_and_authoritative_commit(tmp_path, monkeypatch):
    from gateway.http.routes import chat as routes

    manager = make_turn(tmp_path)
    release = asyncio.Event()

    class Core:
        calls = 0

        async def call_llm_stream(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield '{"action":"answer","content":"draft"'
                await release.wait()
                yield ' INVALID'
            else:
                yield '{"action":"answer","content":"canonical"}'

    core = Core()
    actions = ActionService(conversation_core=core)

    class Conversation:
        async def prepare_chat_turn(self, **kwargs):
            return {"messages": [], "user_config": {}, "reasoning": {}, "execution_budget": {"tool_budget": 3}}

        async def run_chat_loop(self, messages, **kwargs):
            return await actions.run_action(
                goal="g", messages=messages, user_id=kwargs["user_id"], session_id=kwargs["session_id"],
                run_context=kwargs["run_context"], output_sink=kwargs["output_sink"], budget=3,
            )

    server = SimpleNamespace(
        message_manager=manager, conversation_service=Conversation(), config_service=None, reasoning_service=None,
        event_emitter=None, _build_run_context=lambda **_: SimpleNamespace(trace_id="trace"),
        _apply_skill_runtime_context=lambda **_: None,
    )
    monkeypatch.setattr(routes, "get_gateway_server", lambda: server)
    response = await routes.chat(request=routes.ChatRequest(message="hello", session_id="s1", stream=True), raw_request=SimpleNamespace(), user_id="u1")
    iterator = response.body_iterator
    records = []

    def decode(chunk):
        return json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith("data: ")))

    try:
        while not records or records[-1]["type"] != "text":
            records.append(decode(await asyncio.wait_for(anext(iterator), 3)))
        assert records[-1]["content"] == "draft"
        assert not release.is_set()  # The provider has not yet completed its response.
        assert manager.get_messages("s1", user_id="u1") == []
        release.set()
        async for chunk in iterator:
            records.append(decode(chunk))
    finally:
        release.set()
        await iterator.aclose()
    assert any(row.get("operation") == "replace" and row["content"] == "" for row in records)
    assert records[-1]["type"] == "done" and records[-1]["content"] == "canonical"
    assert apply_updates([row for row in records if row["type"] == "text"]) == "canonical"
    assert manager.get_messages("s1", user_id="u1")[-1]["content"] == "canonical"


def test_steering_events_reuse_localized_workbench_activity_contract(tmp_path):
    from gateway.runtime_event_log import RuntimeEventLog
    from gateway.workbench_projection import WorkbenchProjection
    from gateway.task_service import TaskService
    from gateway.workflow_engine import WorkflowEngine

    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    for status in ("pending", "completed"):
        log.append(event_type=f"action.steering.{status}", payload={
            "user_id": "u1", "session_id": "s1", "conversation_turn_id": "t1", "action_loop_id": "a1",
            **ActionService._steering_presentation({"message_id": "m1", "content": "new scope"}, status),
        }, durable=False)
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    projection = WorkbenchProjection(task_service=tasks, workflow_engine=workflows, event_log=log)
    snapshot = projection.snapshot(user_id="u1", session_id="s1")
    assert len(snapshot["timeline"]) == 1
    row = snapshot["timeline"][0]
    assert row["subject_i18n"]["zh"] == "调整执行方向"
    assert row["status"] == "completed"
    assert row["summary"] == "new scope"
