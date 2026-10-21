from __future__ import annotations

import asyncio
import json

import pytest

from gateway.action import ActionService
from gateway.conversation_service import ConversationService
from gateway.goal_gaps import GoalGapState, gap_projection
from gateway.protocol import EventType


class Core:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = []

    async def call_llm(self, messages, **_kwargs):
        self.calls.append(messages)
        action = next(self.actions)
        if callable(action):
            action = action(messages)
        return {"status": "success", "content": json.dumps(action)}


def latest_fact(messages):
    return json.loads(messages[-1]["content"][0]["text"])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["capability_inspect", "capability_request"])
@pytest.mark.parametrize("failure", ["exception", "result", "missing"])
async def test_capability_failures_return_to_model_without_ending_turn(operation, failure):
    action = ({"action": operation, "capability_names": ["browser.open"]} if operation == "capability_inspect"
              else {"action": operation, "objective": "browse", "required_capabilities": ["browser"]})

    async def callback(_):
        if failure == "exception":
            raise FileNotFoundError("dependency is missing")
        return {"error_detail": {"code": "DEPENDENCY_MISSING", "message": "dependency is missing", "category": "capability"}}

    def explain(messages):
        fact = latest_fact(messages)
        assert fact["status"] == "failed"
        assert fact["scope"]["session_id"] == "s"
        assert "recent_obstacles" in messages[0]["content"]
        return {"action": "answer", "content": "The required capability is unavailable; I have not performed the operation.",
                "evidence_refs": [fact["observation_id"]]}

    core = Core([action, explain])
    options = {"capability_inspector" if operation == "capability_inspect" else "capability_resolver":
               None if failure == "missing" else callback}
    out = await ActionService(conversation_core=core).run_action(goal="browse", messages=[], session_id="s", **options)
    assert out["status"] == "success"
    assert len(core.calls) == 2
    assert out["observations"][0]["ok"] is False
    assert out["action_state"]["phase"] == "completed"


@pytest.mark.asyncio
async def test_failed_tool_can_be_repaired_verified_and_used_in_same_loop():
    ready = False
    executed = []

    def choose_repair(messages):
        fact = latest_fact(messages)
        assert fact["error"]["code"] == "DEPENDENCY_MISSING"
        return {"action": "tool_call", "tool_name": "environment.prepare", "args": {},
                "gap_update": {"revision": 0, "create": [{"id": "ready", "kind": "achievement", "requirement": "Environment is ready",
                    "check": {"tool_name": "environment.check", "pointer": "/ready", "expected": True}}],
                    "updates": [{"id": "ready", "state": "blocked", "evidence_refs": [fact["observation_id"]]}]}}

    def finish(messages):
        fact = latest_fact(messages)
        view = json.loads(messages[0]["content"].split("\n", 1)[1])
        return {"action": "answer", "content": "The environment is ready and the requested operation succeeded.",
                "gap_update": {"revision": view["revision"], "updates": [
                    {"id": "ready", "state": "resolved", "evidence_refs": [fact["observation_id"]]}]}}

    # The model, not Runtime, chooses the repair and verification tools.
    core = Core([
        {"action": "tool_call", "tool_name": "browser.open", "args": {}}, choose_repair,
        {"action": "tool_call", "tool_name": "browser.open", "args": {}},
        {"action": "tool_call", "tool_name": "environment.check", "args": {}}, finish,
    ])

    def execute(name, _args):
        nonlocal ready
        executed.append(name)
        if name == "environment.prepare":
            ready = True
        if name == "browser.open" and not ready:
            return {"ok": False, "error_detail": {"code": "DEPENDENCY_MISSING", "message": "Browser dependency missing"}}
        return {"ready": ready}

    out = await ActionService(conversation_core=core).run_action(
        goal="browse", messages=[], tool_executor=execute, budget=5,
    )
    assert out["status"] == "success"
    assert out["goal_progress"]["checks_passed"] == 1
    assert executed == ["browser.open", "environment.prepare", "browser.open", "environment.check"]
    assert len({item["action_loop_id"] for item in out["observations"]}) == 1


@pytest.mark.asyncio
async def test_model_can_explain_unavailable_executor_through_conversation_service():
    core = Core([
        {"action": "tool_call", "tool_name": "browser.open", "args": {}},
        {"action": "answer", "content": "I cannot perform the operation because tool execution is unavailable."},
    ])
    service = ConversationService(conversation_core=core, action_service=ActionService(conversation_core=core))
    out = await service.run_chat_loop([{"role": "user", "content": "browse"}])
    assert out["status"] == "success"
    assert out["observations"][0]["error"]["code"] == "TOOL_EXECUTOR_UNAVAILABLE"
    assert out["execution_path"][0]["executed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_action", [
    {"action": "answer", "content": ""},
    {"action": "answer", "content": "Unsupported claim", "evidence_refs": ["invented"]},
    {"action": "tool_call", "tool_name": "test.run", "args": {}, "procedure_refs": ["invented"]},
])
async def test_multiple_invalid_actions_remain_observations_until_valid_answer(bad_action):
    executed = []
    core = Core([bad_action, bad_action, {"action": "answer", "content": "I cannot substantiate the previous proposal."}])
    out = await ActionService(conversation_core=core).run_action(
        goal="act", messages=[], tool_executor=lambda *args: executed.append(args), budget=3,
    )
    assert out["status"] == "success" and executed == []
    assert len(out["observations"]) == 2
    assert all(item["error"]["code"] == "INVALID_MODEL_ACTION" for item in out["observations"])
    assert all(message["role"] != "assistant" for message in core.calls[-1] if message.get("role") != "system")


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["MODEL_OUTPUT_LIMIT", "MODEL_EMPTY_RESPONSE"])
async def test_model_output_failure_can_recover_without_exposing_diagnostic_as_reply(code):
    class StreamCore:
        calls = 0

        async def call_llm_stream(self, messages, *, result_sink, reasoning_sink, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                await reasoning_sink("provider thinking")
                await result_sink({"status": "error", "code": code, "usage": {"completion_tokens": 2}})
                yield "[error] " + code
            else:
                assert latest_fact(messages)["error"]["code"] == code
                yield '{"action":"answer","content":"I need to split this work into smaller steps."}'

    published = []

    async def sink(text):
        published.append(text)

    out = await ActionService(conversation_core=StreamCore()).run_action(goal="act", messages=[], output_sink=sink)
    assert out["status"] == "success"
    assert "".join(published) == out["content"]
    assert out["usage"]["completion_tokens"] == 2
    assert out["reasoning_steps"][0]["content"] == "provider thinking"


@pytest.mark.asyncio
async def test_budget_exhaustion_asks_model_to_explain_and_never_executes_final_proposal():
    def final(messages):
        facts = [json.loads(message["content"][0]["text"]) for message in messages
                 if isinstance(message.get("content"), list)]
        assert facts[-1]["error"]["code"] == "ACTION_BUDGET_EXHAUSTED"
        return {"action": "answer", "content": "The capability is unavailable; this task remains unfinished."}

    core = Core([{"action": "tool_call", "tool_name": "missing", "args": {}}, final])
    out = await ActionService(conversation_core=core).run_action(goal="act", messages=[], budget=1)
    assert out["status"] == "success" and len(core.calls) == 2
    assert all(item["ok"] is False for item in out["observations"])


@pytest.mark.asyncio
async def test_replanning_cannot_reuse_consumed_approval_by_repeating_a_call_id():
    core = Core([
        {"action": "tool_call", "id": "same", "tool_name": "workspace.write_file", "args": {"path": "first.txt"}},
        {"action": "tool_call", "id": "same", "tool_name": "workspace.write_file", "args": {"path": "other.txt"}},
    ])
    executed = []

    def executor(_name, args):
        executed.append(args)
        raise FileNotFoundError("destination missing")

    service = ActionService(conversation_core=core)
    pending = await service.run_action(goal="write", messages=[], confirmation_resolver=lambda *_: True)
    resumed = await service.resume_action(
        pending=pending, approved_call_id="same", user_config=None, session_id=None, user_id=None,
        run_context=None, tool_executor=executor, confirmation_resolver=lambda *_: True,
    )
    assert resumed["status"] == "needs_confirmation"
    assert resumed["args"] == {"path": "other.txt"}
    assert executed == [{"path": "first.txt"}]


@pytest.mark.asyncio
async def test_observation_audit_failure_stops_execution_instead_of_asking_model_to_override():
    class Emitter:
        async def emit(self, event, *_args, **_kwargs):
            if event == EventType.ACTION_OBSERVATION_COMMITTED:
                raise OSError("audit storage unavailable")

    core = Core([{"action": "capability_inspect", "capability_names": ["test.run"]}])
    out = await ActionService(conversation_core=core, event_emitter=Emitter()).run_action(goal="act", messages=[])
    assert out["status"] == "error" and out["content"] == ""
    assert len(core.calls) == 1


@pytest.mark.asyncio
async def test_capability_cancellation_is_not_reinterpreted_as_a_task_obstacle():
    async def inspect(_):
        raise asyncio.CancelledError

    core = Core([{"action": "capability_inspect", "capability_names": ["test.run"]}])
    with pytest.raises(asyncio.CancelledError):
        await ActionService(conversation_core=core).run_action(goal="act", messages=[], capability_inspector=inspect)


def test_gap_obstacles_are_derived_bounded_and_do_not_invent_semantic_gaps():
    state = GoalGapState()
    observations = [{"observation_id": f"obs_{index}", "tool_name": "test.run", "ok": False,
                     "error": {"code": "MISSING", "message": "x" * 1000}} for index in range(10)]
    view = gap_projection(state, observations=observations, window=4)
    assert len(view["recent_obstacles"]) == 4
    assert view["gaps"] == [] and state.revision == 0
    assert len(json.dumps(view)) < 2400
