"""Deterministic recovery decisions and real dispatch boundaries, not live AI scores."""
from copy import deepcopy
import json

import pytest

from agentkit.mcp.tool_result import ToolErrorInfo, ToolExecutionResult
from gateway.action import ActionService
from gateway.goal_gaps import GoalGapState, admit_gap_action, apply_gap_delta, gap_projection, observe_gap_step
from tests.support.runtime import goal_context, observation_fact, user_choice
from tests.test_goal_gaps import Core, declared, observation


def closed(name, *, retryable=False):
    return ToolExecutionResult(name, False, error=ToolErrorInfo("RESOURCE_CLOSED", "resource closed", "tool", retryable))


def tool(name="resource.read", **args):
    return {"action": "tool_call", "tool_name": name, "args": args}


def recovery(messages, *, name="resource.reopen", strategy="replan", args=None, repairs=None):
    view = goal_context(messages)
    return {**tool(name, **(args or {})), "gap_update": {"revision": view["revision"], "recovery": {
        "strategy": strategy, "reason": "Recheck the failed precondition using another observation",
        "evidence_refs": view["execution_control"]["evidence_refs"], "repair_refs": repairs or []}}}

def wait_for_repair(messages):
    return {"action": "await_user", "content": "Please restore access to the resource",
            "user_dependency": {"kind": "human_action", "reason": "Only the owner can restore this resource.",
                                "evidence_refs": goal_context(messages)["execution_control"]["evidence_refs"]}}


@pytest.mark.parametrize("gaps", ["absent", "open", "blocked"])
def test_varying_arguments_and_error_text_do_not_hide_repeated_failure(gaps):
    state = GoalGapState() if gaps == "absent" else declared()
    if gaps == "blocked":
        state = apply_gap_delta(state, {"revision": state.revision, "updates": [{"id": "artifact", "state": "blocked"}]}, [])
    for i in range(2):
        item = observation(id=f"obs{i}", ok=False, tool="resource.read",
            error={"code": "TEMPORARY_UNAVAILABLE", "category": "transport", "retryable": True, "message": f"volatile {i}"})
        state = observe_gap_step(state, [{"tool_call_id": "call1", "tool_name": "resource.read", "args": {"handle": str(i)}}], [item])
    assert state.recovery.mode == "reassess"
    assert gap_projection(state)["execution_control"]["evidence_refs"] == ["obs1"]


def test_mixed_batch_recovery_cites_the_failure_not_later_successes():
    fail = observation(id="failed", ok=False, error={"code": "CLOSED", "category": "tool", "retryable": False})
    state = observe_gap_step(GoalGapState(), [], [fail, *[observation(id=f"ok{i}") for i in range(6)]])
    assert state.recovery.evidence_refs == ["failed"]


@pytest.mark.asyncio
async def test_failed_batch_is_rejected_before_any_dispatch_or_approval():
    executed, policy, saved = [], [], []
    core = Core([tool(), {"action": "tool_calls", "calls": [
        {"id": "different-id", "tool_name": "resource.read", "args": {}},
        {"tool_name": "external.send", "args": {"text": "must not send"}}]},
        wait_for_repair])

    def execute(name, args):
        executed.append(name)
        return closed(name)

    out = await ActionService(conversation_core=core).run_action(goal="deliver", messages=[], budget=5,
        tool_executor=execute, confirmation_resolver=lambda name, args: policy.append(name) or False,
        checkpoint_sink=lambda value: saved.append(deepcopy(value)))
    assert out["status"] == "needs_input"
    assert executed == policy == ["resource.read"]
    rejected = [row for row in out["observations"] if (row.get("error") or {}).get("code") == "ACTION_REASSESSMENT_REQUIRED"]
    assert len(rejected) == 2
    assert all(not row["executed"] for row in saved[-1]["execution_path"][1:])
    assert any(row["to"] == "reassessing" for row in out["action_state_transitions"])


@pytest.mark.asyncio
async def test_replan_yields_new_evidence_without_inventing_goal_completion():
    executed = []
    core = Core([tool(), lambda messages: recovery(messages), {"action": "answer", "content": "The resource is available; delivery is still unverified."}])

    def execute(name, args):
        executed.append(name)
        return closed(name) if name == "resource.read" else {"connected": True}

    out = await ActionService(conversation_core=core).run_action(goal="deliver", messages=[], budget=4, tool_executor=execute)
    assert executed == ["resource.read", "resource.reopen"] and len(core.calls) == 3
    assert out["goal_gaps"]["recovery"]["mode"] == "execute"
    assert out["goal_progress"]["goal_verification"] == "unknown"


@pytest.mark.asyncio
async def test_one_transient_failure_keeps_a_bounded_retry_without_extra_reflection():
    count = 0

    def execute(name, args):
        nonlocal count
        count += 1
        return closed(name, retryable=True) if count == 1 else {"value": 42}

    core = Core([tool(), tool(), {"action": "answer", "content": "The value is 42"}])
    out = await ActionService(conversation_core=core).run_action(goal="read", messages=[], tool_executor=execute)
    assert count == 2 and len(core.calls) == 3 and out["status"] == "success"
    assert not any(row["to"] == "reassessing" for row in out["action_state_transitions"])


@pytest.mark.asyncio
async def test_recovery_rejections_end_in_model_reply_not_an_infinite_loop():
    executed = []
    core = Core([tool(), tool(), tool("other.read"), {"action": "answer", "content": "I need the unavailable resource restored before proceeding."}])
    out = await ActionService(conversation_core=core).run_action(goal="deliver", messages=[], budget=20,
        tool_executor=lambda name, args: executed.append(name) or closed(name))
    assert executed == ["resource.read"] and len(core.calls) == 4
    assert out["content"] == "I need the unavailable resource restored before proceeding."
    assert out["execution_outcome"]["stop_reason"] == "recovery_exhausted"
    assert out["observations"][-1]["error"]["code"] == "ACTION_RECOVERY_EXHAUSTED"


@pytest.mark.asyncio
async def test_distinct_failed_methods_do_not_exhaust_recovery():
    core = Core([tool(), lambda messages: recovery(messages, args={"variant": 1}),
                 lambda messages: recovery(messages, args={"variant": 2}),
                 wait_for_repair])
    executed = []
    out = await ActionService(conversation_core=core).run_action(goal="deliver", messages=[], budget=20,
        tool_executor=lambda name, args: executed.append((name, args)) or closed(name))
    assert out["status"] == "needs_input" and len(executed) == 3 and len(core.calls) == 4
    assert out["goal_gaps"]["recovery"]["failed_trials"] == 0


@pytest.mark.asyncio
async def test_recovery_permission_survives_approval_restart_but_is_not_approval():
    executed = []
    core = Core([tool(), lambda messages: recovery(messages, name="external.repair"),
                 {"action": "answer", "content": "Repair receipt retained; result still needs checking"}])
    options = dict(goal="repair", messages=[], budget=5, user_id="alice", session_id="s",
        tool_executor=lambda name, args: executed.append(name) or closed(name),
        confirmation_resolver=lambda name, args: name == "external.repair")
    pending = await ActionService(conversation_core=core).run_action(**options)
    assert pending["status"] == "needs_confirmation" and executed == ["resource.read"]
    assert pending["goal_gaps"]["recovery"]["mode"] == "trial"
    resumed = await ActionService(conversation_core=core).resume_action(
        pending=json.loads(json.dumps(pending)), approved_call_id=pending["tool_call_id"], user_config=None,
        user_id="alice", session_id="s", run_context=None, confirmation_resolver=options["confirmation_resolver"],
        tool_executor=lambda name, args: executed.append(name) or {"repaired": True})
    assert resumed["status"] == "success" and executed == ["resource.read", "external.repair"]


@pytest.mark.asyncio
async def test_capability_inspection_is_available_while_reassessing():
    core = Core([tool(), {"action": "capability_inspect", "capability_names": ["resource.reopen"]},
                 user_choice("Please confirm the intended repair")])
    seen = []

    async def inspect(names):
        seen.extend(names)
        return {"tools": names}

    out = await ActionService(conversation_core=core).run_action(goal="repair", messages=[],
        tool_executor=lambda name, args: closed(name), capability_inspector=inspect)
    assert out["status"] == "needs_input" and seen == ["resource.reopen"]


@pytest.mark.asyncio
async def test_mixed_inspection_does_not_turn_execution_into_diagnostic_permission():
    core = Core([tool(), {"action": "tool_calls", "calls": [
        {"action": "capability_inspect", "id": "inspect", "capability_names": ["resource.reopen"]},
        {"tool_name": "external.send", "id": "send", "args": {}}]},
        wait_for_repair])
    seen = []
    async def inspect(names):
        seen.append("inspect")
        return {"tools": names}
    out = await ActionService(conversation_core=core).run_action(goal="repair", messages=[],
        tool_executor=lambda name, args: seen.append(name) or closed(name), capability_inspector=inspect)
    assert out["status"] == "needs_input" and seen == ["resource.read"]
    rejected = [row for row in out["observations"] if (row.get("error") or {}).get("code") == "ACTION_REASSESSMENT_REQUIRED"]
    assert {row["tool_name"] for row in rejected} == {"runtime.capability_inspect", "external.send"}


def test_recovery_rejects_invented_evidence_and_preserves_runtime_owned_state():
    item = observation(ok=False, error={"code": "CLOSED", "category": "tool", "retryable": False})
    state = observe_gap_step(GoalGapState(), [], [item])
    with pytest.raises(ValueError, match="observation"):
        apply_gap_delta(state, {"revision": state.revision, "recovery": {
            "strategy": "replan", "reason": "new method", "evidence_refs": ["invented"]}}, [item])
    with pytest.raises(ValueError):
        apply_gap_delta(state, {"revision": state.revision, "recovery_state": {"mode": "execute"}}, [item])
    assert state.recovery.mode == "reassess"


@pytest.mark.asyncio
async def test_exhausted_wait_restarts_with_user_report_but_not_verified_repair():
    saved = []
    core = Core([tool(), tool(), tool(), wait_for_repair])
    first = await ActionService(conversation_core=core).run_action(goal="deliver", messages=[], budget=20,
        user_id="alice", session_id="s", tool_executor=lambda name, args: closed(name),
        checkpoint_sink=lambda value: saved.append(deepcopy(value)))
    assert first["status"] == "needs_input" and saved[-1]["goal_gaps"]["recovery"]["rejections"] == 2
    checkpoint = json.loads(json.dumps(saved[-1]))
    checkpoint["input_response"] = {"request_id": first["input_request"]["request_id"], "content": "I restored access"}
    executed = []
    # The model must inspect first; a human report cannot replay the failed call.
    resumed_core = Core([tool(), wait_for_repair])
    resumed = await ActionService(conversation_core=resumed_core).run_action(goal="deliver", messages=[],
        user_id="alice", session_id="s", checkpoint=checkpoint,
        tool_executor=lambda name, args: executed.append(name) or {"ready": True})
    assert resumed["status"] == "needs_input" and not executed and len(resumed_core.calls) == 2
    assert resumed["observations"][-1]["error"]["code"] == "ACTION_REASSESSMENT_REQUIRED"


def test_retry_requires_new_success_not_a_user_claim_and_cannot_repeat_forever():
    call = {"tool_name": "resource.read", "args": {}}
    fail = observation(id="failed", tool="resource.read", ok=False,
                       error={"code": "CLOSED", "category": "tool", "retryable": False})
    state = observe_gap_step(GoalGapState(), [{"tool_call_id": "call1", **call}], [fail])
    user = observation(id="user", tool="runtime.user_input")
    repair = observation(id="repair", tool="resource.repair")

    def decision(current, ref, facts):
        return apply_gap_delta(current, {"revision": current.revision, "recovery": {
            "strategy": "retry", "reason": "Recheck after repair", "evidence_refs": ["failed"], "repair_refs": [ref]}}, facts)

    _, denied = admit_gap_action(decision(state, "user", [fail, user]), [call], [fail, user])
    assert denied
    accepted, denied = admit_gap_action(decision(state, "repair", [fail, repair]), [call], [fail, repair])
    assert not denied and accepted.recovery.mode == "trial"
    assert accepted.recovery.failed_calls[0].retries == 1
    # An approval restart may inspect the same permit without granting another retry.
    accepted2, denied = admit_gap_action(GoalGapState.model_validate(accepted.model_dump()), [call], [fail, repair])
    assert not denied and accepted2.recovery.failed_calls[0].retries == 1
    again = {**fail, "observation_id": "failed-again"}
    state = observe_gap_step(accepted, [{"tool_call_id": "call1", **call}], [again])
    newest = observation(id="new-repair", tool="resource.repair")
    state = apply_gap_delta(state, {"revision": state.revision, "recovery": {
        "strategy": "retry", "reason": "Try once more", "evidence_refs": ["failed-again"], "repair_refs": ["new-repair"]}},
        [fail, repair, again, newest])
    _, denied = admit_gap_action(state, [call], [fail, repair, again, newest])
    assert denied


@pytest.mark.asyncio
async def test_monitor_revision_is_visible_before_any_semantic_gap_is_declared():
    def declare(messages):
        view = goal_context(messages)
        assert view["summary"]["tracked"] == 0 and view["revision"] > 0
        return {"action": "answer", "content": "A validation step is still needed", "gap_update": {
            "revision": view["revision"], "create": [{"id": "verify", "kind": "epistemic", "requirement": "Validate the current evidence"}]}}

    out = await ActionService(conversation_core=Core([tool(), declare, {"action": "answer", "content": "Not verified yet."}])).run_action(goal="inspect", messages=[], budget=2,
        tool_executor=lambda name, args: {"value": 42})
    assert out["goal_gaps"]["gaps"][0]["id"] == "verify"
    assert out["execution_outcome"]["goal_status"] == "unverified"
    assert any((row.get("error") or {}).get("code") == "GOAL_UNRESOLVED" for row in out["observations"])


@pytest.mark.asyncio
async def test_independent_task_run_keeps_goals_without_stale_recovery_deadlock(tmp_path):
    from types import SimpleNamespace
    from gateway.task_service import TaskService
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="alice", title="Deliver", objective="Deliver")["task_id"]
    state = observe_gap_step(declared(), [], [observation(ok=False, error={"code": "CLOSED", "category": "tool", "retryable": False})])
    tasks.commit_goal_gaps(task_id=task_id, user_id="alice", state=state, expected_revision=0, expected_objective="Deliver")
    executed = []
    out = await ActionService(conversation_core=Core([tool(), {"action": "answer", "content": "Fresh state inspected"}]), task_service=tasks).run_action(
        goal="Deliver", messages=[], user_id="alice", run_context=SimpleNamespace(task_id=task_id), budget=1,
        tool_executor=lambda name, args: executed.append(name) or {"ready": True})
    assert executed == ["resource.read"] and out["status"] == "success"
    assert out["goal_gaps"]["gaps"][0]["requirement"] == state.gaps[0].requirement
    assert out["goal_progress"]["checks_passed"] == 0


@pytest.mark.asyncio
async def test_open_gap_rejects_unsupported_wait_and_premature_answer_then_allows_checked_completion():
    def finish(messages):
        fact = observation_fact(messages)
        assert fact["status"] == "completed"
        return {"action": "answer", "content": "Verified.", "gap_update": {
            "revision": goal_context(messages)["revision"],
            "updates": [{"id": "verify", "state": "resolved", "evidence_refs": [fact["observation_id"]]}]}}

    core = Core([
        {**user_choice("Which site should I search?"), "gap_update": {"revision": 0,
            "create": [{"id": "verify", "kind": "achievement", "requirement": "Verify the address",
                        "check": {"tool_name": "source.read", "pointer": "/confirmed", "expected": True}}]}},
        {"action": "answer", "content": "Done already."}, tool("source.read"), finish,
    ])
    out = await ActionService(conversation_core=core).run_action(goal="Verify", messages=[], budget=5,
        tool_executor=lambda *_: {"confirmed": True})
    assert out["content"] == "Verified." and out["goal_progress"]["checks_passed"] == 1
    assert "execution_outcome" not in out and not out.get("input_request")
    assert [(row["error"] or {}).get("code") for row in out["observations"]] == [
        "USER_DEPENDENCY_REQUIRED", "GOAL_UNRESOLVED", None]

@pytest.mark.asyncio
async def test_user_only_information_can_pause_with_an_open_gap():
    proposal = {"action": "await_user", "content": "Which building is your office in?", "input_kind": "text",
                "user_dependency": {"kind": "user_information", "reason": "Only the user knows their office building.",
                                    "gap_ids": ["building"]},
                "gap_update": {"revision": 0, "create": [{"id": "building", "kind": "epistemic",
                                                        "requirement": "Identify the user's office building"}]}}
    out = await ActionService(conversation_core=Core([proposal])).run_action(goal="Plan door-to-door travel", messages=[])
    assert out["status"] == "needs_input"
    assert out["input_request"]["input_kind"] == "text" and out["goal_progress"]["open"] == 1


@pytest.mark.asyncio
async def test_invalid_wait_is_not_persisted_even_during_final_completion():
    invalid = {"action": "await_user", "content": "Please do the lookup instead."}
    saved = []
    core = Core([invalid, invalid])
    out = await ActionService(conversation_core=core).run_action(
        goal="Look up a public fact", messages=[], budget=1, checkpoint_sink=saved.append)
    assert not out.get("input_request") and not any(checkpoint.get("pending_input") for checkpoint in saved)
    assert out["execution_outcome"]["goal_status"] == "unverified"
    assert out["execution_outcome"]["response_source"] == "runtime"
    assert out["observations"][0]["error"]["code"] == "USER_DEPENDENCY_REQUIRED"


@pytest.mark.asyncio
async def test_evidenced_block_returns_report_without_completing_goal():
    def blocked(messages):
        fact = observation_fact(messages)
        return {"action": "answer", "content": "The source is unavailable.", "disposition": "blocked", "gap_update": {
            "revision": goal_context(messages)["revision"],
            "updates": [{"id": "verify", "state": "blocked", "evidence_refs": [fact["observation_id"]]}]}}

    core = Core([{**tool("source.read"), "gap_update": {"revision": 0, "create": [
        {"id": "verify", "kind": "epistemic", "requirement": "Verify the source"}]}}, blocked])
    out = await ActionService(conversation_core=core).run_action(goal="Verify", messages=[], tool_executor=lambda name, _: closed(name))
    assert out["execution_outcome"] == {"stop_reason": "goal_blocked", "goal_status": "unverified", "response_source": "model"}
    assert out["goal_progress"]["blocked"] == 1


@pytest.mark.asyncio
async def test_read_only_alternative_uses_registry_without_recovery_packet():
    from types import SimpleNamespace
    from gateway.tools.registry import ToolRegistry
    from gateway.tools.spec import SideEffectLevel, ToolSpec

    registry = ToolRegistry()
    sources = ("source.first", "source.second", "source.third", "source.final")
    for name in sources:
        registry.register_spec(ToolSpec(tool_name=name, side_effect_level=SideEffectLevel.READ_ONLY))
    executed = []

    def execute(name, _):
        executed.append(name)
        return {"value": 42} if name == "source.final" else closed(name)

    core = Core([*(tool(name) for name in sources), {"action": "answer", "content": "Found the answer."}])
    out = await ActionService(conversation_core=core, capability_service=SimpleNamespace(tool_registry=registry)).run_action(
        goal="Find", messages=[], tool_executor=execute)
    assert out["status"] == "success" and executed == list(sources)


@pytest.mark.asyncio
async def test_failed_capability_inspection_cannot_be_repeated_without_repair():
    inspect_action = {"action": "capability_inspect", "capability_names": ["resource.read"]}
    core = Core([inspect_action, inspect_action, wait_for_repair])
    seen = []

    # Capability callbacks return projections; this is an explicit structured failure.
    async def unavailable(names):
        seen.append(names)
        return {"ok": False, "error_detail": {"code": "CLOSED", "message": "closed", "retryable": False}}

    out = await ActionService(conversation_core=core).run_action(goal="inspect", messages=[], capability_inspector=unavailable)
    assert out["status"] == "needs_input" and len(seen) == 1
    assert out["observations"][-1]["error"]["code"] == "ACTION_REASSESSMENT_REQUIRED"


@pytest.mark.asyncio
async def test_unchanged_diagnostic_trials_are_bounded_too():
    inspect_action = {"action": "capability_inspect", "capability_names": ["resource.read"]}
    core = Core([tool(), *[inspect_action] * 4, {"action": "answer", "content": "No new capability evidence; access still needs restoring"}])
    seen = []

    async def inspect(names):
        seen.append(names)
        return {"tools": names}

    out = await ActionService(conversation_core=core).run_action(goal="inspect", messages=[], budget=20,
        user_config={"action": {"gaps": {"window": 2}}}, tool_executor=lambda name, args: closed(name), capability_inspector=inspect)
    assert out["status"] == "success" and len(seen) == 4 and len(core.calls) == 6
    assert out["execution_outcome"]["stop_reason"] == "recovery_exhausted"
