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
async def test_tracked_goal_continues_with_new_evidence_with_or_without_belief(record_belief):
    def second(messages):
        delta = {"revision": goal_context(messages)["revision"]}
        if record_belief:
            delta["belief_updates"] = [{"id": "origin", "gap_id": "locate", "claim": "Found a candidate address",
                                       "evidence_refs": [observation_fact(messages)["observation_id"]]}]
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": 2}, "gap_update": delta}

    def third(messages):
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
        user_config={"action": {"gaps": {"advisory_recovery": False}}},
        tool_executor=lambda _, args: calls.append(args["cursor"]) or {"value": min(args["cursor"], 2)})
    extensions = [row for row in result["action_trace"] if row["event"] == "action.budget_extended"]
    assert len(extensions) == 1
    assert calls == [1, 2, 3, 4]
    assert result["execution_outcome"]["goal_status"] == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("grace", [True, False])
async def test_late_tool_failure_keeps_recent_evidence_for_continuation_and_delivery(grace):
    evidence = []

    def failed_check(messages):
        evidence.append(observation_fact(messages)["observation_id"])
        return {"action": "tool_call", "tool_name": "fixture.check", "args": {"digest": "invalid"}}

    def deliver(messages):
        return {"action": "answer", "content": "Read back the saved result: 49.",
                "evidence_refs": evidence, "gap_update": {
                    "revision": goal_context(messages)["revision"],
                    "updates": [{"id": "report", "state": "resolved", "evidence_refs": evidence}],
                }}

    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {},
         "gap_update": {"revision": 0, "create": [{"id": "report", "kind": "achievement",
                                                  "requirement": "Deliver the checked inventory report"}]}},
        failed_check, deliver,
    ])
    tools = []

    def execute(name, _args):
        tools.append(name)
        if name == "fixture.check":
            raise ValueError("invalid digest")
        return {"closing_count": 49}

    result = await ActionService(conversation_core=model).run_action(
        goal="Deliver the inventory report", messages=[], budget=2,
        allow_progress_grace=grace, tool_executor=execute,
    )
    assert tools == ["fixture.read", "fixture.check"]
    assert any(row["event"] == "action.budget_extended" for row in result["action_trace"]) is grace
    assert any(row["tool_name"] == "runtime.action_budget" for row in result["observations"]) is not grace
    assert "execution_outcome" not in result
    assert result["goal_gaps"]["gaps"][0]["support"] == "reported"
    assert result["goal_progress"]["checks_passed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("initial", "expected_retry"), [(4096, 8192), (8192, 8192)])
async def test_final_response_uses_shared_allowance_and_recovers_real_truncation(initial, expected_retry):
    allowances = []

    class Model(ScriptedModel):
        async def call_llm(self, messages, *, user_config, **kwargs):
            allowances.append((user_config["_runtime_call"]["purpose"], user_config["api"]["max_tokens"]))
            return await super().call_llm(messages, **kwargs)

    model = Model([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {}},
        {"status": "error", "code": "MODEL_OUTPUT_LIMIT", "content": "Partial answer",
         "usage": {"completion_tokens": initial}},
        "The file was read; further verification remains.",
    ])
    executed = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect a file", messages=[], budget=1,
        tool_executor=lambda name, _: executed.append(name) or {"value": 49},
        user_config={"api": {"max_tokens": initial, "output_token_limit": 8192}},
    )
    assert allowances == [("action", initial), ("final_response", initial), ("final_response", expected_retry)]
    assert executed == ["fixture.read"]
    assert result["content"] == "The file was read; further verification remains."
    assert result["execution_outcome"]["response_source"] == "model"
    assert result["usage"]["completion_tokens"] == initial


@pytest.mark.asyncio
async def test_final_truncation_recovery_stops_if_admission_closes():
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {}},
        {"status": "error", "code": "MODEL_OUTPUT_LIMIT", "usage": {"completion_tokens": 8192}},
        {"status": "error", "code": "MODEL_ADMISSION_CLOSED"},
    ])
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect a file", messages=[], budget=1, tool_executor=lambda *_: {"value": 49},
        user_config={"api": {"max_tokens": 8192}},
    )
    assert len(model.calls) == 3
    assert result["completion_error"]["code"] == "MODEL_ADMISSION_CLOSED"
    assert result["execution_outcome"]["response_source"] == "runtime"
    assert result["usage"]["completion_tokens"] == 8192


@pytest.mark.asyncio
async def test_repeated_evidence_cannot_renew_after_checkpoint_restore():
    def read(i):
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": i}}

    model = ScriptedModel([read(i) for i in (1, 2, 3, 4, 5)] + ["Stopped with partial findings."])
    calls, checkpoints = [], []

    def execute(target, args):
        cursor = args["cursor"]
        target.append(cursor)
        return {"value": min(cursor, 3)}

    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect a changing value", messages=[], budget=1, allow_progress_grace=True,
        tool_executor=lambda _, args: execute(calls, args),
        checkpoint_sink=checkpoints.append,
    )
    assert calls == [1, 2, 3, 4, 5] and len(model.calls) == 6
    assert result["execution_outcome"]["stop_reason"] == "budget_exhausted"
    assert checkpoints[-1]["budget"] == 5
    assert sum(row["event"] == "action.budget_extended" for row in result["action_trace"]) == 2
    saved = next(row for row in checkpoints if row["step"] == 3 and row["budget"] == 5)
    restarted = ScriptedModel([read(4), read(5), "Stopped with partial findings."])
    replayed = []
    resumed = await ActionService(conversation_core=restarted).run_action(
        goal="Inspect a changing value", messages=[], budget=1, allow_progress_grace=True,
        tool_executor=lambda _, args: execute(replayed, args),
        checkpoint=saved,
    )
    assert replayed == [4, 5] and len(restarted.calls) == 3
    assert sum(row["event"] == "action.budget_extended" for row in resumed["action_trace"]) == 2


@pytest.mark.asyncio
async def test_repeated_renewal_can_cross_the_old_fifty_step_cap():
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": i}}
        for i in range(1, 53)
    ] + [{"action": "answer", "content": "Read all 52 records."}])
    seen = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Read all records", messages=[], budget=48, allow_progress_grace=True,
        tool_executor=lambda _, args: seen.append(args["cursor"]) or args,
    )
    assert seen == list(range(1, 53))
    assert [row["payload"]["step"] for row in result["action_trace"]
            if row["event"] == "action.budget_extended"] == [48, 50, 52]
    assert "execution_outcome" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [False, True])
async def test_tracked_renewal_does_not_require_a_gap_update_to_dispatch(linked):
    def read(cursor):
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": cursor}}

    def review(messages):
        assert any("after new evidence" in str(row.get("content")) for row in messages)
        action = read(4)
        if linked:
            action["gap_update"] = {"revision": goal_context(messages)["revision"],
                                    "belief_updates": [{"id": "sample", "gap_id": "report", "claim": "Found a usable record",
                                                        "evidence_refs": [observation_fact(messages)["observation_id"]]}]}
        return action

    first = {**read(1), "gap_update": {"revision": 0, "create": [
        {"id": "report", "kind": "achievement", "requirement": "Inspect all relevant records"},
    ]}}
    model = ScriptedModel([first, read(2), read(3), review, read(5), "The report is incomplete."])
    seen = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect the records", messages=[], budget=1, allow_progress_grace=True,
        tool_executor=lambda _, args: seen.append(args["cursor"]) or {"value": min(args["cursor"], 3)},
    )
    assert seen == [1, 2, 3, 4, 5]
    grants = [row["payload"] for row in result["action_trace"] if row["event"] == "action.budget_extended"]
    assert [row["step"] for row in grants] == [1, 3]
    assert grants[-1]["progress"] == "new_observation"
    assert result["execution_outcome"]["response_source"] == "model"


@pytest.mark.asyncio
async def test_model_can_continue_without_gap_update_then_close_goal_with_evidence():
    def read(cursor):
        return {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": cursor}}

    def update(messages, state):
        return {"revision": goal_context(messages)["revision"], "updates": [
            {"id": "report", "state": state, "evidence_refs": [observation_fact(messages)["observation_id"]]},
        ]}

    def finish(messages):
        return {"action": "answer", "content": "All three records were read.",
                "gap_update": update(messages, "resolved")}

    first = {**read(1), "gap_update": {"revision": 0, "create": [
        {"id": "report", "kind": "achievement", "requirement": "Read three records"},
    ]}}
    model = ScriptedModel([first, read(2), read(3), finish])
    seen = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Read three records", messages=[], budget=1, allow_progress_grace=True,
        user_config={"action": {"progress_grace_steps": 1}},
        tool_executor=lambda _, args: seen.append(args["cursor"]) or args,
    )
    assert seen == [1, 2, 3]
    assert [row["payload"]["step"] for row in result["action_trace"]
            if row["event"] == "action.budget_extended"] == [1, 2, 3]
    assert result["goal_gaps"]["gaps"][0]["support"] == "reported"
    assert "execution_outcome" not in result


@pytest.mark.asyncio
async def test_renewal_window_expiry_still_allows_model_wrapup(monkeypatch):
    from gateway.action import service as action_service

    clock = SimpleNamespace(time=lambda: 1000, perf_counter=action_service.time.perf_counter)
    monkeypatch.setattr(action_service, "time", clock)
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "fixture.read", "args": {"cursor": i}} for i in (1, 2)
    ] + ["Two records were read; more remain."])

    def execute(_, args):
        if args["cursor"] == 2:
            clock.time = lambda: 1001
        return args

    # Anchor the persisted extension timestamp to the same clock used for admission.
    from gateway.action import models
    monkeypatch.setattr(models, "time", clock)
    result = await ActionService(conversation_core=model).run_action(
        goal="Inspect the records", messages=[], budget=1, allow_progress_grace=True,
        user_config={"action": {"progress_grace_steps": 1, "progress_grace_seconds": 1}},
        tool_executor=execute,
    )
    assert [row["payload"]["step"] for row in result["action_trace"]
            if row["event"] == "action.budget_extended"] == [1]
    assert result["content"] == "Two records were read; more remain."
    assert result["execution_outcome"]["response_source"] == "model"


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
    repeated = [failure] if isinstance(failure, dict) and failure.get("code") == "MODEL_OUTPUT_LIMIT" else []
    model = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.write_file", "args": {}}, failure, *repeated,
    ])
    executed = []
    result = await ActionService(conversation_core=model).run_action(
        goal="Create UI", messages=[], budget=1,
        user_config={"api": {"max_tokens": 8192}},
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
        assert result["usage"]["completion_tokens"] == 14


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
