import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from config import GoalGapConfig, PrometheaConfig
from gateway.action import ActionService
from gateway.goal_gaps import GoalGapState, answer_disposition, apply_gap_delta, gap_outcome, gap_projection, observe_gap_step, reasoning_delivery_gaps
from gateway.public_contracts import Task
from gateway.public_views import public_task
from gateway.task_service import TaskService, TaskRevisionConflict, TaskExecutionConflict
from tests.support.runtime import observation_fact, goal_context


SPEC = {"id": "artifact", "kind": "achievement", "requirement": "The exported document passes validation",
        "check": {"tool_name": "document.validate", "pointer": "/valid", "expected": True}}


def declared():
    return apply_gap_delta(GoalGapState(), {"revision": 0, "create": [SPEC], "focus": ["artifact"]}, [])


def observation(value=None, *, ok=True, id="obs1", tool="document.validate", error=None):
    return {"observation_id": id, "tool_call_id": "call1", "tool_name": tool, "ok": ok,
            "structured_result": value if value is not None else {"valid": True},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "error": error}


def resolve(state, ref="obs1"):
    return {"revision": state.revision, "updates": [{"id": "artifact", "state": "resolved", "evidence_refs": [ref]}]}


class Core:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def call_llm(self, messages, **kwargs):
        self.calls.append(messages)
        response = self.responses.pop(0)
        payload = response(messages) if callable(response) else response
        return {"status": "success", "content": json.dumps(payload)}


def last_observation(messages):
    return observation_fact(messages)


def current_revision(messages):
    return goal_context(messages)["revision"]


@pytest.mark.asyncio
async def test_budget_progress_report_cannot_cite_trial_as_verified_delivery():
    def premature_report(messages):
        gap = goal_context(messages)["gaps"][0]
        assert gap["state"] == "open"
        return {"action": "answer", "content": "Verified route from the requested address",
                "evidence_refs": [trial_refs[0]]}

    trial_refs = []
    def second_step(messages):
        trial_refs.append(last_observation(messages)["observation_id"])
        return {"action": "tool_call", "tool_name": "document.validate", "args": {}}

    core = Core([{"action": "tool_call", "tool_name": "route.trial", "args": {},
                  "gap_update": {"revision": 0, "create": [SPEC]}}, second_step, premature_report])
    out = await ActionService(conversation_core=core).run_action(
        goal="Deliver a verified result", messages=[], budget=2,
        tool_executor=lambda *_: {"valid": False})
    assert out["execution_outcome"]["response_source"] == "runtime"
    assert out["execution_outcome"]["goal_status"] == "unverified"
    assert "Verified route" not in out["content"]


def test_reasoning_proposals_keep_only_independent_checks_with_selected_prerequisites():
    child = {**SPEC, "id": "child", "depends_on": ["artifact"], "check": {
        **SPEC["check"], "bindings": [{"gap_id": "artifact", "pointer": "/id", "source_pointer": "/id"}]}}
    proposals = reasoning_delivery_gaps("tree", [
        child, SPEC, {**SPEC, "id": "pruned", "depends_on": ["absent"]},
        {**SPEC, "id": "aggregate", "check": {**SPEC["check"], "tool_name": "reasoning.run"}},
    ])
    parent, dependent = proposals
    assert parent["id"] != "artifact"
    assert dependent["depends_on"] == [parent["id"]]
    assert dependent["check"]["bindings"][0]["gap_id"] == parent["id"]
    assert parent["id"] == reasoning_delivery_gaps("tree", [SPEC])[0]["id"]


@pytest.mark.asyncio
async def test_selected_reasoning_step_gates_answer_until_independent_verification(tmp_path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Export", objective="Export")["task_id"]
    proposals = reasoning_delivery_gaps("tree", [SPEC])
    gap_id = proposals[0]["id"]

    def premature(messages):
        assert goal_context(messages)["gaps"][0]["id"] == gap_id
        assert tasks.get_task(task_id)["goal_gaps"]["gaps"][0]["state"] == "open"
        return {"action": "answer", "content": "Done"}

    def verify(messages):
        assert "GOAL_UNRESOLVED" in str(messages)
        return {"action": "tool_call", "tool_name": "document.validate", "args": {}}

    def final(messages):
        return {"action": "answer", "content": "Validated", "gap_update": {
            "revision": current_revision(messages), "updates": [{"id": gap_id, "state": "resolved",
                "evidence_refs": [last_observation(messages)["observation_id"]]}]}}

    core = Core([{"action": "tool_call", "tool_name": "reasoning.run", "args": {"objective": "Export"}},
                 premature, verify, final])
    out = await ActionService(conversation_core=core, task_service=tasks).run_action(
        goal="Export", messages=[], user_id="u", session_id="s", run_context=SimpleNamespace(task_id=task_id),
        tool_executor=lambda name, *_: {"delivery_gaps": proposals} if name == "reasoning.run" else {"valid": True})
    assert out["status"] == "success"
    assert out["goal_progress"]["checks_passed"] == 1
    assert tasks.get_task(task_id)["goal_gaps"]["gaps"][0]["state"] == "resolved"


def test_checks_are_real_but_not_proof_of_full_goal_coverage():
    state = declared()
    resolved = apply_gap_delta(state, resolve(state), [observation()])
    assert resolved.gaps[0].support == "checked"
    assert gap_outcome(resolved)["checks_passed"] == 1
    assert gap_outcome(resolved)["goal_verification"] == "unknown"
    assert gap_projection(resolved)["gaps"][0]["id"] == "artifact"
    assert state.gaps[0].state == "open"


def test_task_belief_is_candidate_only_and_duplicate_sources_do_not_add_progress():
    state = declared()
    state.recovery.mode = "trial"
    page = observation({"address": "58 West Road"}, id="page", tool="search")
    state = observe_gap_step(state, [], [page])
    assert state.recovery.mode == "reassess"
    assert not state.recent[-1].progress and not state.recent[-1].candidate_progress
    belief = {"id": "origin", "gap_id": "artifact", "claim": "Found a candidate address", "evidence_refs": ["page"]}
    delta = {"revision": state.revision, "belief_updates": [belief]}
    with pytest.raises(ValueError, match="successful Runtime observations"):
        apply_gap_delta(state, delta, [])
    state = apply_gap_delta(state, delta, [page])
    assert state.recent[-1].candidate_progress and not state.recent[-1].progress
    assert state.recovery.mode == "reassess"
    assert gap_projection(state)["candidate_beliefs"][0] == belief
    assert GoalGapState.model_validate_json(state.model_dump_json()) == state

    other = observation({"address": "58 West Road"}, id="other", tool="lookup")
    state = observe_gap_step(state, [], [other])
    duplicate = {**belief, "id": "same_address", "evidence_refs": ["other"]}
    unchanged = apply_gap_delta(state, {"revision": state.revision, "belief_updates": [duplicate]}, [page, other])
    assert unchanged == state and not unchanged.recent[-1].candidate_progress
    checked = apply_gap_delta(state, resolve(state), [page, other, observation()])
    assert checked.recent[-1].progress and checked.recovery.mode == "execute"


@pytest.mark.parametrize("item", [
    observation({"valid": False}), observation({"valid": 1}), observation(ok=False),
    observation(tool="another.tool"), observation(id="invented"), observation({}),
    observation(ok=False, error={"category": "approval", "code": "USER_DECLINED"}),
])
def test_bad_evidence_cannot_resolve_gap(item):
    state = declared()
    with pytest.raises(ValueError):
        apply_gap_delta(state, resolve(state), [item])
    assert state.revision == 1 and state.gaps[0].support == "none"


def test_checks_must_precede_evidence_and_reopening_invalidates_prior_receipt():
    old = observation()
    state = apply_gap_delta(GoalGapState(), {"revision": 0, "create": [SPEC]}, [old])
    with pytest.raises(ValueError, match="check did not pass"):
        apply_gap_delta(state, resolve(state), [old])
    receipt = observation()
    receipt["observation_id"] = "obs2"
    state = apply_gap_delta(state, resolve(state, "obs2"), [old, receipt])
    state = apply_gap_delta(state, {"revision": state.revision, "updates": [{"id": "artifact", "state": "open"}]}, [old, receipt])
    assert state.gaps[0].support == "none"
    with pytest.raises(ValueError):
        apply_gap_delta(state, resolve(state, "obs2"), [old, receipt])
    assert apply_gap_delta(state, resolve(state, "fresh"), [old, receipt, observation(id="fresh")]).gaps[0].support == "checked"


def test_semantic_resolution_remains_inferred_and_gap_identity_is_immutable():
    spec = {key: value for key, value in SPEC.items() if key != "check"}
    state = apply_gap_delta(GoalGapState(), {"revision": 0, "create": [spec]}, [])
    state = apply_gap_delta(state, resolve(state), [observation()])
    assert state.gaps[0].support == "inferred"
    assert state.gaps[0].state == "open"
    assert gap_outcome(state)["checks_passed"] == 0
    with pytest.raises(ValueError, match="cannot complete"):
        answer_disposition(state, blocked=False, observations=[])
    for delta in ({"revision": 0}, {"revision": state.revision, "create": [spec]},
                  {"revision": state.revision, "delete": ["artifact"]}):
        with pytest.raises(ValueError):
            apply_gap_delta(state, delta, [])
    earlier = observation()
    state = apply_gap_delta(state, {"revision": state.revision, "updates": [
        {"id": "artifact", "state": "open", "check": SPEC["check"]}]}, [earlier])
    with pytest.raises(ValueError, match="check did not pass"):
        apply_gap_delta(state, resolve(state), [earlier])
    checked = apply_gap_delta(state, resolve(state, "fresh"), [earlier, observation(id="fresh")])
    assert checked.gaps[0].support == "checked"


@pytest.mark.parametrize("tool, pointer, expected, reason", [
    ("web.search", "/results/0/title", True, "value type"),
    ("web.fetch_json", "/status", 200, "Transport metadata"),
])
def test_registered_output_schema_rejects_invalid_goal_checks(tool, pointer, expected, reason):
    from agentkit.tools.standard.web_tools import WebFetchJsonTool, WebSearchTool

    schemas = {"web.fetch_json": WebFetchJsonTool.output_schema, "web.search": WebSearchTool.output_schema}
    spec = {**SPEC, "check": {"tool_name": tool, "pointer": pointer, "expected": expected}}
    with pytest.raises(ValueError, match=reason):
        apply_gap_delta(GoalGapState(), {"revision": 0, "create": [spec]}, [], output_schema=schemas.__getitem__)


@pytest.mark.asyncio
async def test_model_can_deliver_semantic_result_with_unchecked_prerequisite():
    gaps = [
        {"id": "source", "kind": "epistemic", "requirement": "Identify the relevant source"},
        {"id": "summary", "kind": "achievement", "requirement": "Deliver an evidence-based summary",
         "depends_on": ["source"]},
    ]

    def deliver(messages):
        ref = last_observation(messages)["observation_id"]
        return {"action": "answer", "content": "The source supports the conclusion, with limits.",
                "evidence_refs": [ref], "gap_update": {"revision": current_revision(messages), "updates": [
                    {"id": gap["id"], "state": "resolved", "evidence_refs": [ref]} for gap in reversed(gaps)
                ]}}

    model = Core([{"action": "tool_call", "tool_name": "document.read", "args": {},
                   "gap_update": {"revision": 0, "create": gaps}}, deliver])
    out = await ActionService(conversation_core=model).run_action(
        goal="Summarize the source", messages=[], tool_executor=lambda *_: {"text": "Source contents"})
    assert out["status"] == "success" and out.get("execution_outcome") is None
    assert [(gap["state"], gap["support"]) for gap in out["goal_gaps"]["gaps"]] == [
        ("resolved", "inferred"), ("resolved", "reported")]
    assert out["goal_progress"]["checks_passed"] == 0
    assert out["goal_progress"]["goal_verification"] == "unknown"
    assert GoalGapState.model_validate(out["goal_gaps"]).gaps[1].state == "resolved"


def test_semantic_delivery_is_not_committed_with_other_outstanding_work():
    spec = {key: value for key, value in SPEC.items() if key != "check"}
    state = apply_gap_delta(GoalGapState(), {"revision": 0, "create": [
        spec, {"id": "source", "kind": "epistemic", "requirement": "Verify the source"}]}, [])
    with pytest.raises(ValueError, match="other tracked gaps"):
        apply_gap_delta(state, resolve(state), [observation()], allow_inferred_delivery=True)
    assert state.gaps[0].state == "open"


def test_capacity_and_short_projection_do_not_discard_outstanding_ids():
    state = GoalGapState()
    for offset in range(0, 12, 6):
        state = apply_gap_delta(state, {"revision": state.revision, "create": [
            {"id": "gap" + str(i), "kind": "epistemic", "requirement": "A" * 400} for i in range(offset, offset + 6)
        ]}, [])
    projection = gap_projection(state)
    assert len(json.dumps(projection, ensure_ascii=False)) <= 2400
    assert {item["id"] for item in projection["gaps"]} == {gap.id for gap in state.gaps}
    with pytest.raises(ValueError, match="capacity"):
        apply_gap_delta(state, {"revision": state.revision, "create": [{"id": "extra", "kind": "epistemic", "requirement": "more"}]}, [])
    with pytest.raises(ValueError, match="must fit"):
        GoalGapConfig(max_gaps=32, context_chars=1200)


def test_monitor_ignores_confirmation_and_recognizes_repeated_runtime_results():
    state = declared()
    assert observe_gap_step(state, [], [observation(ok=False, error={"category": "approval"})]).recent == []
    for i in range(3):
        state = observe_gap_step(state, [{"tool_call_id": "call1", "tool_name": "document.validate", "args": {}}], [observation(id=f"obs{i}")], window=3)
    assert "recovery" in gap_projection(state, window=3)
    state = apply_gap_delta(state, resolve(state), [observation()])
    assert "recovery" not in gap_projection(state, window=3)


def test_nonfinite_result_does_not_break_optional_monitoring():
    state = declared()
    assert observe_gap_step(state, [], [observation({"value": float("nan")})]) is state


def test_distinct_text_only_mcp_results_are_not_treated_as_identical():
    state = declared()
    for i in range(4):
        item = observation(id=f"obs{i}")
        item["structured_result"] = None
        item["model_projection"] = [{"type": "text", "text": f"Different evidence {i}"}]
        state = observe_gap_step(state, [], [item])
    assert "recovery" not in gap_projection(state)


def test_checks_remain_visible_without_explicit_focus():
    state = apply_gap_delta(GoalGapState(), {"revision": 0, "create": [SPEC]}, [])
    assert gap_projection(state)["focus_checks"]["artifact"] == SPEC["check"]


def test_dependent_check_requires_verified_matching_input_and_reopens_on_change():
    location = {"id": "place", "kind": "epistemic", "requirement": "Verify origin",
                "check": {"tool_name": "places.lookup", "pointer": "/matched", "expected": True}}
    route = {"id": "route", "kind": "achievement", "requirement": "Calculate route from verified origin",
             "depends_on": ["place"], "check": {"tool_name": "routing.plan", "pointer": "/ok", "expected": True,
                 "bindings": [{"gap_id": "place", "pointer": "/origin", "source_pointer": "/coordinates"}]}}
    state = apply_gap_delta(GoalGapState(), {"revision": 0, "create": [route, location]}, [])

    def fact(id, name, value):
        return {"observation_id": id, "tool_name": name, "ok": True, "structured_result": value}

    def resolve(id, ref):
        return {"id": id, "state": "resolved", "evidence_refs": [ref]}

    trial = fact("trial", "routing.plan", {"ok": True, "origin": [1, 2]})
    place = fact("place", "places.lookup", {"matched": True, "coordinates": [1, 2]})
    wrong = fact("wrong", "routing.plan", {"ok": True, "origin": [4, 5]})
    correct = fact("correct", "routing.plan", {"ok": True, "origin": [1, 2]})
    with pytest.raises(ValueError, match="prerequisites"):
        apply_gap_delta(state, {"revision": 1, "updates": [resolve("route", "trial")]}, [trial])
    for ref in ("trial", "wrong"):
        with pytest.raises(ValueError, match="declared check did not pass"):
            apply_gap_delta(state, {"revision": 1, "updates": [resolve("route", ref), resolve("place", "place")]},
                            [trial, place, wrong])
    checked = apply_gap_delta(state, {"revision": 1, "updates": [resolve("route", "correct"), resolve("place", "place")]},
                              [trial, place, wrong, correct])
    reopened = apply_gap_delta(checked, {"revision": 2, "updates": [{"id": "place", "state": "open"}]},
                               [trial, place, wrong, correct])
    assert all(gap.state == "open" and not gap.evidence_refs for gap in reopened.gaps)


def test_cyclic_goal_dependencies_are_rejected():
    parent = {**SPEC, "depends_on": ["other"]}
    child = {**SPEC, "id": "other", "depends_on": [SPEC["id"]]}
    with pytest.raises(ValueError, match="cycles"):
        apply_gap_delta(GoalGapState(), {"revision": 0, "create": [parent, child]}, [])


@pytest.mark.asyncio
async def test_confirmation_restores_task_scope_to_new_request_context(tmp_path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    first = {"action": "tool_call", "tool_name": "document.validate", "args": {},
             "gap_update": {"revision": 0, "create": [SPEC]}}
    def verified(messages):
        obs = last_observation(messages)
        return {"action": "answer", "content": "Finished", "gap_update": {
            "revision": current_revision(messages), "updates": [{"id": "artifact", "state": "resolved",
                "evidence_refs": [obs["observation_id"]]}]}}

    core = Core([first, verified])
    service = ActionService(conversation_core=core, task_service=tasks)
    pending = await service.run_action(goal="Goal", messages=[], user_id="u", session_id="s",
                                       run_context=SimpleNamespace(task_id=task_id, task_run_id=None), confirmation_resolver=lambda *_: True)
    context = SimpleNamespace(task_id=None, task_run_id=None)
    out = await service.resume_action(pending=pending, approved_call_id=pending["tool_call_id"], user_config=None,
                                      session_id="s", user_id="u", run_context=context,
                                      tool_executor=lambda *_: {"valid": True}, confirmation_resolver=None)
    assert context.task_id == task_id and out["status"] == "success"
    assert tasks.get_task(task_id)["goal_gaps"]["revision"] == out["goal_gaps"]["revision"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidation", ["objective", "paused", "lease", "user", "session"])
async def test_confirmation_cannot_execute_after_task_or_identity_changes(tmp_path, invalidation):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    tasks.start_run(task_id=task_id, user_id="u", run_id="r", run_type="test")
    token = tasks.claim_execution(task_id=task_id, user_id="u", run_id="r", owner_id="worker")
    first = {"action": "tool_call", "tool_name": "document.validate", "args": {}}
    service = ActionService(conversation_core=Core([first]), task_service=tasks)
    pending = await service.run_action(goal="Goal", messages=[], user_id="u", session_id="s",
                                       run_context=SimpleNamespace(task_id=task_id, task_run_id="r", execution_token=token),
                                       confirmation_resolver=lambda *_: True)
    if invalidation == "objective":
        tasks.update_task(task_id=task_id, user_id="u", objective="Changed")
    elif invalidation == "paused":
        tasks.transition_task(task_id=task_id, user_id="u", status="paused")
    elif invalidation == "lease":
        tasks._tasks[task_id]["executions"]["r"]["epoch"] += 1
    with pytest.raises((TaskExecutionConflict, PermissionError)):
        await service.resume_action(pending=pending, approved_call_id=pending["tool_call_id"], user_config=None,
                                    session_id="other" if invalidation == "session" else "s",
                                    user_id="other" if invalidation == "user" else "u", run_context=SimpleNamespace(),
                                    tool_executor=lambda *_: pytest.fail("stale approval must not execute"), confirmation_resolver=None)


@pytest.mark.asyncio
async def test_task_pause_during_model_call_prevents_tool_execution_without_gap_delta(tmp_path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    def pause_and_propose(_):
        tasks.transition_task(task_id=task_id, user_id="u", status="paused")
        return {"action": "tool_call", "tool_name": "write", "args": {}}
    out = await ActionService(conversation_core=Core([pause_and_propose]), task_service=tasks).run_action(
        goal="Goal", messages=[], user_id="u", run_context=SimpleNamespace(task_id=task_id),
        tool_executor=lambda *_: pytest.fail("paused task must not execute"))
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_simple_reply_has_one_call_and_no_gap_projection():
    core = Core([{"action": "answer", "content": "Hello"}])
    out = await ActionService(conversation_core=core).run_action(goal="Hello", messages=[{"role": "user", "content": "Hello"}])
    assert len(core.calls) == 1 and "goal_gaps" not in out
    assert not any("Runtime goal gaps" in str(message.get("content")) for message in core.calls[0])


@pytest.mark.asyncio
async def test_main_model_updates_gaps_with_no_sentinel_call_and_no_delta_history():
    def final(messages):
        obs = last_observation(messages)
        return {"action": "answer", "content": "Validated", "gap_update": {
            "revision": current_revision(messages), "updates": [{"id": "artifact", "state": "resolved", "evidence_refs": [obs["observation_id"]]}]}}
    core = Core([{"action": "tool_call", "tool_name": "document.validate", "args": {},
                  "gap_update": {"revision": 0, "create": [SPEC], "focus": ["artifact"]}}, final])
    out = await ActionService(conversation_core=core).run_action(goal="Export", messages=[{"role": "user", "content": "Export"}], tool_executor=lambda *_: {"valid": True})
    assert len(core.calls) == 2 and out["goal_progress"]["checks_passed"] == 1
    assert '"gap_update"' not in core.calls[1][-2]["content"]
    assert sum("Runtime goal gaps" in str(message.get("content")) for message in core.calls[1]) == 1


@pytest.mark.asyncio
async def test_invalid_gap_delta_does_not_add_retry_or_replace_valid_assistant_reply():
    core = Core([{"action": "tool_call", "tool_name": "read", "args": {}, "gap_update": {"revision": 99}},
                 {"action": "answer", "content": "Here is the result"}])
    out = await ActionService(conversation_core=core).run_action(goal="Read", messages=[], tool_executor=lambda *_: {"text": "data"})
    assert out["status"] == "success" and out["content"] == "Here is the result"
    assert len(core.calls) == 2 and "update_rejected" in str(core.calls[1])


@pytest.mark.asyncio
async def test_confirmation_checkpoint_restores_gap_state_on_refusal():
    first = {"action": "tool_call", "tool_name": "document.validate", "args": {}, "gap_update": {"revision": 0, "create": [SPEC]}}
    def declined(messages):
        obs = last_observation(messages)
        return {"action": "answer", "content": "Not executed", "disposition": "blocked", "gap_update": {
            "revision": current_revision(messages), "updates": [{"id": "artifact", "state": "blocked",
                "evidence_refs": [obs["observation_id"]]}]}}

    service = ActionService(conversation_core=Core([first, declined]))
    pending = await service.run_action(goal="Validate", messages=[], confirmation_resolver=lambda *_: True)
    assert pending["goal_gaps"]["gaps"][0]["state"] == "open"
    rejected = await service.reject_pending_action(pending=pending, user_config=None, session_id="s", user_id="u", run_context=None,
                                                  tool_executor=lambda *_: pytest.fail("must not execute"), confirmation_resolver=None)
    assert rejected["goal_gaps"]["gaps"][0]["state"] == "blocked" and rejected["goal_gaps"]["recent"] == []
    assert rejected["execution_outcome"]["stop_reason"] == "goal_blocked"


def test_task_gap_state_is_durable_isolated_and_prevents_false_completion(tmp_path):
    path = str(tmp_path / "tasks.json")
    service = TaskService(storage_path=path)
    task = service.create_task(user_id="alice", title="Export", objective="Export correctly")
    task_id = task["task_id"]
    state = declared()
    service.commit_goal_gaps(task_id=task_id, user_id="alice", state=state, expected_revision=0, expected_objective="Export correctly")
    service.start_run(task_id=task_id, user_id="alice", run_id="run1", run_type="test")
    service.update_run(task_id=task_id, user_id="alice", run_id="run1", status="completed")
    assert service.get_task(task_id)["status"] == "waiting_user"
    restarted = TaskService(storage_path=path)
    assert restarted.get_task(task_id)["goal_gaps"] == state.model_dump()
    with pytest.raises(KeyError):
        restarted.commit_goal_gaps(task_id=task_id, user_id="bob", state=state, expected_revision=0, expected_objective="Export correctly")
    view = Task.model_validate(public_task(restarted.get_task(task_id))).model_dump()["goal_gaps"]
    assert view is not None and "recent" not in view and "barriers" not in view
    progress = public_task(restarted.get_task(task_id))["goal_progress"]
    assert progress == {"revision": state.revision, "tracked": 1, "open": 1, "blocked": 0,
                        "resolved": 0, "checks_passed": 0, "goal_verification": "unknown"}
    restored = TaskService(storage_path=str(tmp_path / "copy.json"))
    restored.import_user_state(user_id="alice", payload=restarted.export_user_state(user_id="alice"))
    assert restored.get_task(task_id)["goal_gaps"] == state.model_dump()
    assert public_task(restored.get_task(task_id))["goal_progress"] == progress
    restarted.update_task(task_id=task_id, user_id="alice", objective="Different goal")
    with pytest.raises(TaskExecutionConflict):
        restarted.commit_goal_gaps(task_id=task_id, user_id="alice", state=state, expected_revision=0, expected_objective="Export correctly")
    assert "goal_gaps" not in restarted.get_task(task_id)
    assert public_task(restarted.get_task(task_id))["goal_progress"]["tracked"] == 0


def test_task_gap_commits_reject_stale_writers_and_execution_epochs(tmp_path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = service.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    service.start_run(task_id=task_id, user_id="u", run_id="r", run_type="test")
    token = service.claim_execution(task_id=task_id, user_id="u", run_id="r", owner_id="worker")
    state = declared()
    stale = {**token, "epoch": token["epoch"] - 1}
    with pytest.raises(TaskExecutionConflict):
        service.commit_goal_gaps(task_id=task_id, user_id="u", state=state, expected_revision=0, expected_objective="Goal", execution_token=stale)
    service.commit_goal_gaps(task_id=task_id, user_id="u", state=state, expected_revision=0, expected_objective="Goal", execution_token=token)
    with pytest.raises(TaskRevisionConflict):
        service.commit_goal_gaps(task_id=task_id, user_id="u", state=state, expected_revision=0, expected_objective="Goal", execution_token=token)
    assert service.get_task(task_id)["goal_gaps"]["revision"] == 1


@pytest.mark.asyncio
async def test_action_uses_durable_task_gap_state_across_runtime_instances(tmp_path):
    path = str(tmp_path / "tasks.json")
    tasks = TaskService(storage_path=path)
    task_id = tasks.create_task(user_id="u", title="Export", objective="Export")["task_id"]
    context = SimpleNamespace(task_id=task_id, task_run_id=None)
    first = Core([{"action": "answer", "content": "Need validation", "gap_update": {"revision": 0, "create": [SPEC]}},
                  {"action": "answer", "content": "Validation still pending."}])
    await ActionService(conversation_core=first, task_service=tasks).run_action(goal="Export", messages=[], user_id="u", run_context=context, budget=1)
    assert context.goal_gaps["summary"]["open"] == 1
    tasks = TaskService(storage_path=path)
    def final(messages):
        obs = last_observation(messages)
        return {"action": "answer", "content": "Validated", "gap_update": {
            "revision": current_revision(messages), "updates": [{"id": "artifact", "state": "resolved", "evidence_refs": [obs["observation_id"]]}]}}
    core = Core([{"action": "tool_call", "tool_name": "document.validate", "args": {}}, final])
    out = await ActionService(conversation_core=core, task_service=tasks).run_action(goal="Continue", messages=[], user_id="u", run_context=context, tool_executor=lambda *_: {"valid": True})
    assert out["goal_progress"]["checks_passed"] == 1
    assert len(core.calls) == 2 and tasks.get_task(task_id)["goal_gaps"]["gaps"][0]["support"] == "checked"


@pytest.mark.asyncio
async def test_gap_disabled_and_batch_concurrency_are_unchanged():
    core = Core([{"action": "tool_calls", "calls": [{"tool_name": "one", "args": {}}, {"tool_name": "two", "args": {}}],
                  "gap_update": {"revision": 0, "create": [SPEC]}}, {"action": "answer", "content": "Done"}])
    out = await ActionService(conversation_core=core).run_action(goal="Batch", messages=[], user_config={"action": {"gaps": {"enabled": False}}}, tool_executor=lambda *_: {"valid": True})
    assert len(out["observations"]) == 2 and len(core.calls) == 2 and "goal_gaps" not in out


def test_task_goal_commit_rolls_back_in_memory_when_persistence_fails(tmp_path, monkeypatch):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    previous = tasks.get_task(task_id)
    def fail():
        raise OSError("disk unavailable")
    monkeypatch.setattr(tasks, "_persist", fail)
    with pytest.raises(OSError):
        tasks.commit_goal_gaps(task_id=task_id, user_id="u", state=declared(), expected_revision=0, expected_objective="Goal")
    assert tasks.get_task(task_id) == previous


def test_gap_env_configuration_uses_existing_root_settings(monkeypatch):
    monkeypatch.setenv("ACTION__GAPS__WINDOW", "7")
    assert PrometheaConfig().action.gaps.window == 7


def test_resolving_last_gap_recomputes_parent_task_and_logs_only_changes(tmp_path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task_id = tasks.create_task(user_id="u", title="Goal", objective="Goal")["task_id"]
    state = declared()
    tasks.commit_goal_gaps(task_id=task_id, user_id="u", state=state, expected_revision=0, expected_objective="Goal")
    tasks.start_run(task_id=task_id, user_id="u", run_id="r", run_type="test")
    tasks.update_run(task_id=task_id, user_id="u", run_id="r", status="completed")
    assert tasks.get_task(task_id)["status"] == "waiting_user"
    finished = apply_gap_delta(state, resolve(state), [observation()])
    tasks.commit_goal_gaps(task_id=task_id, user_id="u", state=finished, expected_revision=state.revision, expected_objective="Goal")
    task = tasks.get_task(task_id)
    assert task["status"] == "completed"
    changed = [event for event in task["events"] if event["event_type"] == "goal.gaps.updated"][-1]["payload"]
    assert changed["changes"][0]["support"] == "checked" and "goal_gaps" not in changed
