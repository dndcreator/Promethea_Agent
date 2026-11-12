"""Regression of the calculator incident at the real ActionService boundary."""
import asyncio
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.completion import parse_final_answer
from gateway.action.model_action import InvalidModelAction, parse_model_action
from tests.support.runtime import ScriptedModel, goal_context, observation_fact


@pytest.mark.parametrize("text", ["The file is saved; preview remains unverified.", '{"action":"answer","content":"Saved, not verified."}'])
def test_final_answer_accepts_prose_and_legacy_answer_envelopes(text):
    assert parse_final_answer(text).kind == "answer"


@pytest.mark.parametrize("text", ["", '{"action":"tool_call","tool_name":"delete","args":{}}', '{"action":"answer","content":', '<calls>delete</calls>', '```json\n{"action":"tool_call","tool_name":"delete","args":{}}\n```'])
def test_final_answer_never_promotes_structured_instructions_to_prose(text):
    with pytest.raises(InvalidModelAction):
        parse_final_answer(text)


def test_execution_protocol_remains_strict_for_plain_prose():
    with pytest.raises(InvalidModelAction):
        parse_model_action("I wrote the file.")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unchanged", "no_result", "failed", "cost_limit", "strict"])
async def test_step_grace_requires_new_successful_tool_evidence_and_no_hard_budget(mode):
    calls = []

    def execute(_, args):
        calls.append(args["attempt"])
        if mode == "failed" and len(calls) == 2:
            raise ValueError("test failure")
        if mode == "no_result":
            return {}
        return {"value": 1 if mode == "unchanged" else len(calls)}

    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {"attempt": i}} for i in (1, 2)
    ] + ["The remaining work is unverified."])
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect a changing value", messages=[], budget=2, tool_executor=execute,
        allow_progress_grace=mode != "strict", run_context=SimpleNamespace(cost_budget=.10) if mode == "cost_limit" else None,
    )
    assert calls == [1, 2] and len(model.calls) == 3
    assert result["execution_outcome"]["stop_reason"] == "budget_exhausted"
    assert not any(row["event"] == "action.budget_extended" for row in result["action_trace"])


@pytest.mark.asyncio
@pytest.mark.parametrize("record_belief", [False, True])
async def test_tracked_goal_continues_past_soft_limit_only_with_recent_progress(record_belief):
    def second(messages):
        delta = {"revision": goal_context(messages)["revision"]}
        if record_belief:
            delta["belief_updates"] = [{"id": "origin", "gap_id": "locate", "claim": "Found a candidate address",
                                       "evidence_refs": [observation_fact(messages)["observation_id"]]}]
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": 2}, "gap_update": delta}

    def third(messages):
        if not record_belief:
            return "The origin remains unverified."
        assert any("Runtime granted 2 additional decisions" in str(row.get("content")) for row in messages)
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": 3}}

    model = ScriptedModel([{"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": 1},
                            "gap_update": {"revision": 0, "create": [{"id": "locate", "kind": "epistemic",
                                                                     "requirement": "Verify the origin"}]}},
                           second, third, {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": 4}},
                           "The origin remains unverified."])
    calls = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Verify the origin", messages=[], budget=2, allow_progress_grace=True,
        tool_executor=lambda _, args: calls.append(args["cursor"]) or args)
    extensions = [row for row in result["action_trace"] if row["event"] == "action.budget_extended"]
    assert len(extensions) == int(record_belief)
    assert calls == ([1, 2, 3, 4] if record_belief else [1, 2])
    assert result["execution_outcome"]["goal_status"] == "unverified"


@pytest.mark.asyncio
async def test_new_evidence_cannot_renew_an_already_granted_extension():
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": i}} for i in (1, 2, 3)
    ] + ["Stopped with partial findings."])
    calls, checkpoints = [], []
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect a changing value", messages=[], budget=1, allow_progress_grace=True,
        tool_executor=lambda _, args: calls.append(args["cursor"]) or args,
        checkpoint_sink=checkpoints.append,
    )
    assert calls == [1, 2, 3] and len(model.calls) == 4
    assert result["execution_outcome"]["stop_reason"] == "budget_exhausted"
    assert checkpoints[-1]["budget"] == 3 and checkpoints[-1]["progress_grace_steps"] == 0
    assert sum(row["event"] == "action.budget_extended" for row in result["action_trace"]) == 1
    saved = next(row for row in checkpoints if row["step"] == 1 and row["budget"] == 3)
    restarted = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": i}} for i in (2, 3)
    ] + ["Stopped with partial findings."])
    replayed = []
    resumed = await ActionService(conversation_core=restarted).run_action(
        goal="Inspect a changing value", messages=[], budget=1, allow_progress_grace=True,
        tool_executor=lambda _, args: replayed.append(args["cursor"]) or args,
        checkpoint=saved,
    )
    assert replayed == [2, 3] and len(restarted.calls) == 3
    assert sum(row["event"] == "action.budget_extended" for row in resumed["action_trace"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_written_file_survives_budget_exhaustion_with_plain_model_reply(tmp_path, stream):
    content = '<button onclick="this.textContent=2+2">Calculate</button>'
    model = ScriptedModel([
        {"action": "tool_call", "id": "write", "tool_name": "workspace.write_file", "args": {"path": "calculator.html", "content": content}},
        "The file is saved. Canvas mounting and interaction remain unverified.",
    ])
    calls, updates, checkpoints = [], [], []

    def execute(name, args):
        calls.append(name)
        (tmp_path / args["path"]).write_text(args["content"], encoding="utf-8")
        return {"path": args["path"], "size": len(args["content"])}

    async def publish(update):
        updates.append(update)

    result = await ActionService(conversation_core=model).run_action(
        goal="Create an interactive calculator", messages=[], budget=1,
        tool_executor=execute, checkpoint_sink=checkpoints.append,
        output_sink=publish if stream else None,
    )
    assert result["status"] == "success"
    assert result["content"].startswith("The file is saved.")
    assert result["execution_outcome"]["goal_status"] == "unverified"
    assert result["execution_outcome"]["response_source"] == "model"
    assert (tmp_path / "calculator.html").read_text(encoding="utf-8") == content
    assert calls == ["workspace.write_file"]
    assert result["observations"][0]["ok"] is True
    assert checkpoints[-1]["result"]["content"] == result["content"]
    if stream:
        assert updates[-1] == result["content"]
        assert not any('"action"' in str(update) for update in updates)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    {"status": "error", "code": "MODEL_OUTPUT_LIMIT", "error": "truncated", "usage": {"completion_tokens": 7}},
    {"action": "tool_call", "tool_name": "dangerous.write", "args": {}},
    '{"action":"answer","content":',
    ConnectionError("provider disconnected"),
])
async def test_final_failure_keeps_observations_and_returns_runtime_notice(failure):
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {}}, failure,
    ])
    executed = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Create UI", messages=[], budget=1,
        tool_executor=lambda name, _: executed.append(name) or {"path": "calculator.html"},
    )
    assert executed == ["workspace.write_file"]
    assert result["status"] == "success" and result["content"].startswith("Runtime:")
    assert "calculator.html" in result["content"]
    assert result["execution_outcome"]["response_source"] == "runtime"
    assert result["execution_outcome"]["goal_status"] == "unverified"
    assert result["observations"][0]["ok"] is True
    assert result["observations"][-1]["tool_name"] == "runtime.completion"
    if isinstance(failure, dict) and failure.get("usage"):
        assert result["usage"]["completion_tokens"] == 7


@pytest.mark.asyncio
async def test_final_completion_does_not_swallow_cancellation():
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "read", "args": {}}, asyncio.CancelledError(),
    ])
    with pytest.raises(asyncio.CancelledError):
        await ActionService(conversation_core=model).run_action(goal="act", messages=[], budget=1, tool_executor=lambda *_: {})


@pytest.mark.asyncio
async def test_answer_only_completion_recovers_without_reexecuting_tools():
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {}},
        {"status": "error", "code": "MODEL_TRANSPORT_TRANSIENT", "usage": {"usage_complete": False}},
        "The file is saved; interaction remains unverified.",
    ])
    calls = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Create UI", messages=[], budget=1,
        tool_executor=lambda name, _: calls.append(name) or {"path": "index.html"},
    )
    assert calls == ["workspace.write_file"]
    assert model.calls[1] == model.calls[2]
    assert result["content"] == "The file is saved; interaction remains unverified."
    assert result["execution_outcome"]["response_source"] == "model"
    assert result["usage"]["usage_complete"] is False


@pytest.mark.asyncio
async def test_exhausted_transport_retries_do_not_send_an_extra_final_request():
    failure = {"status": "error", "code": "MODEL_TRANSPORT_TRANSIENT", "usage": {"usage_complete": False}}
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {}}, failure, failure,
    ])
    writes = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Create UI", messages=[], budget=4, user_config={"action": {"max_model_recoveries": 1}},
        tool_executor=lambda name, _: writes.append(name) or {"path": "index.html"},
    )
    assert writes == ["workspace.write_file"] and len(model.calls) == 3
    assert result["execution_outcome"]["response_source"] == "runtime"
    assert result["execution_outcome"]["goal_status"] == "unverified"
    assert "index.html" in result["content"]


@pytest.mark.asyncio
async def test_explicit_continuation_uses_committed_facts_without_replaying_write(tmp_path):
    from copy import deepcopy

    checkpoints, writes = [], []
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "calculator.html"}},
        "File saved; browser validation is still needed.",
    ])

    def write(_, args):
        writes.append(args["path"])
        (tmp_path / args["path"]).write_text("calculator", encoding="utf-8")
        return {"path": args["path"]}

    service = ActionService(conversation_core=model)
    first = await service.run_action(goal="Create UI", messages=[], budget=1, tool_executor=write, checkpoint_sink=checkpoints.append)
    checkpoint = deepcopy(checkpoints[-1])
    assert await service.run_action(goal="Create UI", messages=[], checkpoint=checkpoint) == first

    def continue_from_facts(messages):
        assert "calculator.html" in str(messages)
        return {"action": "answer", "content": "The saved file remains available; verification is still outstanding."}

    resumed = await ActionService(conversation_core=ScriptedModel([continue_from_facts])).run_action(
        goal="Create UI", messages=[], budget=2, checkpoint={**checkpoint, "resume_result": True},
        tool_executor=write,
    )
    assert writes == ["calculator.html"]
    assert resumed["action_run_id"] != first["action_run_id"]
    assert resumed["observations"][0] == first["observations"][0]
    assert any(row["event"] == "action.continued" for row in resumed["action_trace"])
    assert checkpoint == checkpoints[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [("version", 99), ("goal", "different objective"), ("transitions", [])])
async def test_continuation_validates_checkpoint_version_goal_and_settled_phase(key, value):
    checkpoints = []
    service = ActionService(conversation_core=ScriptedModel([
        {"action": "tool_call", "tool_name": "read", "args": {}}, "Inspection is incomplete.",
    ]))
    await service.run_action(goal="Inspect", messages=[], budget=1, tool_executor=lambda *_: {}, checkpoint_sink=checkpoints.append)
    checkpoint = {**checkpoints[-1], key: value, "resume_result": True}
    with pytest.raises(ValueError):
        await service.run_action(goal="Inspect", messages=[], checkpoint=checkpoint)
