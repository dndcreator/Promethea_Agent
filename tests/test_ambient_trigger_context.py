"""Admission facts survive attention-window turnover, without LLM interpretation."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.public_contracts import AmbientSettings
from gateway.runtime_event_log import RuntimeEventLog
from gateway.self_model_service import SelfModelService
from tests.test_ambient_service import Core, setup
from tests.test_background_agents import drain


@pytest.mark.asyncio
async def test_pinned_trigger_resolves_from_log_after_window_rollover_and_restart(tmp_path):
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter(event_log=log)
    model = SelfModelService(event_emitter=emitter, workspace_root=str(tmp_path))
    await emitter.emit(EventType.ENVIRONMENT_STATE_CHANGED, {"user_id": "alice", "check": "release", "conclusion": "failure", "detail": "CI-ORCHID-29"})
    trigger = deepcopy(model.state.get("alice").changes[-1])
    for number in range(30):
        await emitter.emit(EventType.UI_CONTEXT_CHANGED, {"user_id": "alice", "number": number})
    restored = SelfModelService(event_emitter=EventEmitter(event_log=RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))), workspace_root=str(tmp_path))
    context = restored.working_context("alice", trigger=trigger)
    assert trigger["event_id"] not in [row["event_id"] for row in context["changes"]]
    assert "CI-ORCHID-29" in context["trigger_observation"]["payload_excerpt"]
    assert context["trigger_observation"]["truncated"] is False
    assert restored.working_context("bob", trigger=trigger)["trigger_observation"] is None
    assert restored.working_context("alice", trigger={**trigger, "event_id": "spoof"})["trigger_observation"] is None
    assert restored.working_context("alice", trigger={**trigger, "seq": 999999})["trigger_observation"] is None


@pytest.mark.asyncio
async def test_activation_uses_admitted_trigger_not_later_scene(tmp_path):
    tasks, runtime, conversation, _, ambient = setup(tmp_path, Core())
    log = RuntimeEventLog(storage_path=str(tmp_path / "pinned-events.jsonl"))
    emitter = EventEmitter(event_log=log)
    conversation.event_emitter = ambient.self_model.event_emitter = emitter
    for event in (EventType.ENVIRONMENT_STATE_CHANGED, EventType.UI_CONTEXT_CHANGED):
        emitter.on(event, ambient.self_model.observe)
        emitter.on(event, ambient._observe)
    ambient.event_log = log
    direction = "Continuously maintain release reliability"
    ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction=direction))
    await conversation.event_emitter.emit(EventType.ENVIRONMENT_STATE_CHANGED, {"user_id": "alice", "detail": "original-trigger"})
    ambient.recover()
    task = tasks.execution_tasks(run_type="ambient")[0]
    run = task["runs"][-1]
    await conversation.event_emitter.emit(EventType.UI_CONTEXT_CHANGED, {"user_id": "alice", "detail": "later-change"})
    captured = {}

    async def turn(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "content": "No warranted action."}

    original = conversation.run_ambient_turn
    conversation.run_ambient_turn = turn
    try:
        token = tasks.claim_execution(task_id=task["task_id"], user_id="alice", run_id=run["run_id"], owner_id="trigger-test")
        await ambient.run(task, run, token)
        cognition = captured["situation"]["cognition"]
        assert "original-trigger" in cognition["trigger_observation"]["payload_excerpt"]
        assert captured["situation"]["initiative"]["last_trigger"] == run["metadata"]["trigger"]
        assert tasks.get_task(task["task_id"], user_id="alice")["objective"] == direction
    finally:
        conversation.run_ambient_turn = original
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_ambient_progress_uses_real_checks_and_remains_a_continuing_goal(tmp_path):
    from tests.support.runtime import ScriptedModel, observation_fact, goal_context

    def final(messages):
        fact = observation_fact(messages)
        return {"action": "answer", "content": "The current check passed.", "gap_update": {
            "revision": goal_context(messages)["revision"], "updates": [
                {"id": "release", "state": "resolved", "evidence_refs": [fact["observation_id"]]}]}}

    core = ScriptedModel([{"action": "tool_call", "tool_name": "fixture.check", "args": {}, "gap_update": {
        "revision": 0, "create": [{"id": "release", "kind": "achievement", "requirement": "Current release check is valid",
        "check": {"tool_name": "fixture.check", "pointer": "/valid", "expected": True}}]}}, final])
    tasks, runtime, conversation, _, ambient = setup(tmp_path, core)

    async def check(args, ctx=None):
        return {"valid": True}

    conversation.capability_service.register_tool(SimpleNamespace(tool_id="fixture.check", name="fixture.check",
        description="Read the actual isolated check result", side_effect_level="read_only", invoke=check))
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Maintain release reliability"))
        await drain(runtime)
        task = tasks.execution_tasks(run_type="ambient")[0]
        assert task["goal_gaps"]["gaps"][0]["support"] == "checked"
        assert task["goal_gaps"]["gaps"][0]["state"] == "resolved"
        assert task["runs"][-1]["status"] == "completed"
        assert task["status"] == "waiting_user"  # One check never completes a continuous objective.
    finally:
        await runtime.shutdown()
