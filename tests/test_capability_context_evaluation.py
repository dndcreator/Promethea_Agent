"""The paired evaluator must not manufacture completion or compare censored cost."""
import json
import pytest

from scripts.evaluate_capability_context import summarize_pair, function_ast, request_stability
from tests.support.runtime_efficiency import calculator_result_matches


@pytest.mark.parametrize("value,accepted", [("5", True), ("5.0", True), ("2 + 3 = 5", True),
    ("2 + 3 = 6", False), ("2 + 2 = 5", False), ("100 - 95 = 5", False),
    ("__import__('os').system('x') = 5", False), ("nan", False), ("inf", False), ("5 = 5 = 5", False)])
def test_calculator_criterion_checks_actual_result_without_executing_display_text(value, accepted):
    assert calculator_result_matches(value, 2, 3, 5) is accepted


def test_calculator_criterion_accepts_negative_decimal_equations():
    assert calculator_result_matches("-2.5 + 1 = -1.5", -2.5, 1, -1.5)


def result(condition, **overrides):
    return {"case": "calculator", "condition": condition, "calls": 2, "admission_denied": [],
            "usage_known": True, "cost_usd": .01, "delivery_verified": False, **overrides}


def test_pair_requires_both_arms_and_does_not_treat_reply_as_delivery():
    assert not summarize_pair([result("baseline")], "calculator")["paired"]
    summary = summarize_pair([result("baseline"), result("candidate", cost_usd=.005)], "calculator")
    assert summary["paired"] and summary["cost_change_percent"] == -50
    assert summary["delivery_verified"] == {"baseline": False, "candidate": False}


def test_censored_or_unknown_spend_never_scores_a_cost_win():
    for override in ({"calls": 0}, {"admission_denied": [{"state": "not_sent"}]},
                     {"usage_known": False, "cost_usd": None}, {"driver_error": "timeout"}):
        summary = summarize_pair([result("baseline"), result("candidate", **override)], "calculator")
        assert not summary["paired"] and summary["cost_change_percent"] is None
        assert "incomplete or censored" in summary["goal_quality_conclusion"]


def test_external_attempt_never_claims_account_delivery_from_transport_success():
    rows = [result(name, case="github") for name in ("baseline", "candidate")]
    summary = summarize_pair(rows, "github")
    assert summary["paired"] and "unverified external" in summary["goal_quality_conclusion"]
    assert not any(summary["delivery_verified"].values())


def test_protected_function_comparison_ignores_positions_but_not_execution_changes(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text("class Service:\n    def call(self):\n        return True\n")
    original = function_ast(path, "Service", "call")
    path.write_text("\n\nclass Service:\n    def call(self):\n        return True\n")
    assert function_ast(path, "Service", "call") == original
    path.write_text("class Service:\n    def call(self):\n        return False\n")
    assert function_ast(path, "Service", "call") != original


def test_stability_metrics_distinguish_real_rewrites_and_mixed_proposals():
    def event(value, tools, operations):
        return {"event_type": "model.call.recorded", "payload": {
            "model_step_id": str(value), "purpose": "action",
            "provider_message": {"tool_calls": [{"function": {"name": name}} for name in operations]},
            "wire_request": {"tools": tools, "messages": [{"role": "tool", "content": json.dumps({
                "observations": [{"observation_id": "obs", "result": value}]})}]}}}
    same = event(1, ["inspect", "tool"], ["capability_inspect", "tool_call"])
    missing_wire = {"event_type": "model.call.recorded", "payload": {"model_step_id": "denied", "provider_status": "error"}}
    metrics = request_stability([same, missing_wire, same, event(2, ["answer"], []), missing_wire])
    assert metrics["function_definition_changes"] == 1
    assert len(metrics["prior_observation_rewrites"]) == 1
    assert metrics["native_batches"][0]["mixed_query_and_tool"] is True
    assert not metrics["native_batches"][-1]["mixed_query_and_tool"]
