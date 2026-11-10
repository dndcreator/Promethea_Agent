"""Cost reductions are accepted only with retained evidence and bounded recovery."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.observation import RuntimeObservation
from gateway.action.recovery import recover
from gateway.delegation import child_configuration
from gateway.http.metrics import MetricsCollector
from gateway.model_usage import merge_usage
from gateway.runtime_io import ContextCompiler, replace_context, ENVIRONMENT_CONTEXT
from gateway.prompt_assembler import PromptAssembler
from scripts.evaluate_runtime_efficiency import ReplayModel
from tests.support.evaluation import Budget, BudgetExceeded
from tests.support.runtime_efficiency import eval_settings, paired_summary


@pytest.mark.asyncio
@pytest.mark.parametrize("required,limits", [(3000, [2000, 4000, 4000]), (6000, [2000, 4000, 8000, 8000])])
async def test_truncation_changes_real_request_allowance_before_one_committed_write(required, limits):
    core = ReplayModel({"mode": "output", "required_output": required})
    writes = []
    result = await ActionService(conversation_core=core).run_action(
        goal="write", messages=[], user_config={"api": {"max_tokens": 2000, "output_token_limit": 8192}},
        tool_executor=lambda name, args: writes.append((name, args)) or {"path": args["path"]},
    )
    assert result["status"] == "success"
    assert [row["max_tokens"] for row in core.calls] == limits
    assert len(writes) == 1
    assert sum(row.get("error", {}).get("code") == "MODEL_OUTPUT_LIMIT" for row in result["observations"] if row.get("error")) == len(limits) - 2


def test_recovery_never_exceeds_caller_ceiling_and_stops_identical_protocol_output():
    state = {}
    assert recover(state, code="MODEL_OUTPUT_LIMIT", signature="s", initial=500, ceiling=500, retries=2)[0]
    assert not recover(state, code="MODEL_OUTPUT_LIMIT", signature="s", initial=500, ceiling=500, retries=2)[0]
    state = {}
    assert recover(state, code="INVALID_MODEL_ACTION", signature="same", initial=1000, ceiling=4000, retries=2)[0]
    assert not recover(state, code="INVALID_MODEL_ACTION", signature="same", initial=1000, ceiling=4000, retries=2)[0]
    config = child_configuration({"api": {"max_tokens": 4000, "output_token_limit": 8192}}, {"child_max_tokens": 500})
    assert config["api"]["max_tokens"] == config["api"]["output_token_limit"] == 500


def test_dynamic_replacement_preserves_user_text_and_static_prefix():
    original = [{"role": "system", "content": "fixed safety policy"}, {"role": "user", "content": "old observation"},
                {"role": "user", "name": ENVIRONMENT_CONTEXT, "content": "old observation"}]
    updated = replace_context(original, ENVIRONMENT_CONTEXT, "new observation")
    updated = replace_context(updated, ENVIRONMENT_CONTEXT, "newest observation")
    assert updated[:2] == original[:2]
    assert len(updated) == 3 and updated[-1]["content"] == "newest observation"
    context = SimpleNamespace(tool_availability={})
    assembler = PromptAssembler()
    first = assembler.refresh_tool_message(updated, tools=[], snapshot={"snapshot_id": "one", "generated_at": "first", "registry_revision": "same"}, run_context=context)
    second = assembler.refresh_tool_message(first, tools=[], snapshot={"snapshot_id": "two", "generated_at": "second", "registry_revision": "same"}, run_context=context)
    assert [row for row in first if row["role"] == "system"] == [row for row in second if row["role"] == "system"]
    assert sum(row.get("name") == "promethea_capabilities" for row in second) == 1


def test_projection_prioritizes_recent_batch_and_retains_exact_small_facts():
    observations = [RuntimeObservation(action_loop_id="a", model_step_id="s", tool_call_id=str(i), tool_name="read", ok=True,
        structured_result={"body": "x" * 20000, "revision": i, "count": 29}) for i in range(4)]
    messages = [{"role": "user", "content": row.model_content()} for row in observations]
    original = deepcopy(messages)
    projected = ContextCompiler.project_observations(messages, [row.as_dict() for row in observations], per_result_chars=4000, total_chars=8000)
    facts = [json.loads(row["content"][0]["text"]) for row in projected]
    assert len(facts[-1]["result"]["preview"]) > len(facts[0]["result"]["preview"])
    assert facts[-1]["result"]["summary"]["revision"] == 3
    assert facts[-1]["result"]["summary"]["count"] == 29
    assert original == messages
    assert all(row["result"]["read_more"]["args"]["observation_id"] == row["observation_id"] for row in facts)


def test_paged_observation_projection_does_not_create_recursive_read_or_skip_content():
    source = json.dumps({"content": "abc" * 10000})
    page = {"observation_id": "original", "field": "result", "offset": 100, "total_chars": len(source),
            "content": source[100:12100], "next_offset": 12100, "source_truncated": False}
    row = RuntimeObservation(action_loop_id="a", model_step_id="s", tool_call_id="c", tool_name="runtime.read_observation", ok=True, structured_result=page)
    projected = ContextCompiler.project_observations([{"role": "user", "content": row.model_content()}], [row.as_dict()], per_result_chars=2000, total_chars=4000)
    result = json.loads(projected[0]["content"][0]["text"])["result"]
    assert result["observation_id"] == "original" and "read_more" not in result
    assert result["next_offset"] == 100 + len(result["content"]) > 100
    assert result["content"] == source[100:result["next_offset"]]
    assert page["next_offset"] == 12100


def test_history_projection_stays_stable_until_budget_pressure_and_never_wraps_previews():
    rows = [RuntimeObservation(action_loop_id="a", model_step_id=str(i), tool_call_id=str(i), tool_name="read", ok=True,
        structured_result={"body": "x" * 20000, "count": i}) for i in range(3)]
    compiler = ContextCompiler.project_observations
    first = compiler([{"role": "user", "content": rows[0].model_content()}], [rows[0].as_dict()],
                     per_result_chars=4000, total_chars=8000)
    repeated = compiler(first, [rows[0].as_dict()], per_result_chars=4000, total_chars=8000)
    assert first == repeated
    expanded = compiler([*first, {"role": "user", "content": rows[1].model_content()}], [row.as_dict() for row in rows[:2]],
                        per_result_chars=4000, total_chars=8000)
    assert expanded[0] == first[0]
    pressured = compiler([*expanded, {"role": "user", "content": rows[2].model_content()}], [row.as_dict() for row in rows],
                         per_result_chars=4000, total_chars=8000)
    facts = [json.loads(row["content"][0]["text"]) for row in pressured]
    original = json.loads(first[0]["content"][0]["text"])["result"]
    assert facts[0]["result"]["content_hash"] == original["content_hash"]
    assert facts[0]["result"]["total_chars"] == original["total_chars"]
    assert facts[0]["result"]["preview"].startswith('{"body":')
    assert sum(len(json.dumps(fact["result"], ensure_ascii=False, sort_keys=True)) for fact in facts) <= 8000


def test_cache_usage_and_metrics_never_report_missing_cache_tokens_as_zero():
    total = {"prompt_tokens": 0, "completion_tokens": 0}
    merge_usage(total, {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 80}})
    assert total["prompt_cache_hit_tokens"] == 80
    merge_usage(total, {"prompt_tokens": 100, "completion_tokens": 5})
    assert total["prompt_cache_hit_tokens"] is None and total["cache_usage_complete"] is False
    metrics = MetricsCollector()
    metrics.record_llm_call(0.1, 100, 5, usage={"prompt_tokens": 100, "prompt_cache_hit_tokens": 80}, purpose="action")
    metrics.record_llm_call(0.1, 100, 5, purpose="memory_verify")
    stats = metrics.get_stats()["llm"]
    assert stats["cached_prompt_tokens"] is None
    assert stats["cache_reported_calls"] == 1
    assert stats["by_purpose"]["memory_verify"]["calls"] == 1


def test_evaluation_admission_rejects_before_spend_and_stops_unknown_billing():
    budget = Budget(max_cost_usd=0.0001)
    with pytest.raises(BudgetExceeded, match="currency"):
        budget.admit([{"role": "user", "content": "test"}], 1000, (0.3, 1.2))
    assert budget.calls == 0 and budget.cost_usd == 0
    budget.max_cost_usd = 0.1
    budget.admit([], 1000, (0.3, 1.2))
    budget.settle(None, (0.3, 1.2))
    with pytest.raises(BudgetExceeded, match="unavailable"):
        budget.admit([], 1000, (0.3, 1.2))
    assert budget.calls == 1 and not budget.usage_known


def test_evaluation_settings_require_separate_credentials_and_finite_budget(tmp_path):
    path = tmp_path / ".env.eval"
    values = {
        "PROMETHEA_EVAL_AGENT_BASE_URL": "https://example.invalid/v1",
        "PROMETHEA_EVAL_AGENT_API_KEY": "evaluation-only",
        "PROMETHEA_EVAL_AGENT_MODEL": "fixture",
        "PROMETHEA_EVAL_AGENT_INPUT_USD_PER_MILLION": "0.3",
        "PROMETHEA_EVAL_AGENT_OUTPUT_USD_PER_MILLION": "1.2",
        "PROMETHEA_EVAL_MAX_COST_USD": "0.1",
    }
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    _, ceiling, rates = eval_settings(path)
    assert ceiling == 0.1 and rates == (0.3, 1.2)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\nPRODUCT_API_KEY=must-not-be-consumed\n")
    with pytest.raises(ValueError, match="evaluation-only"):
        eval_settings(path)
    path.write_text("\n".join(f"{key}={value}" for key, value in {**values, "PROMETHEA_EVAL_MAX_COST_USD": "nan"}.items()), encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        eval_settings(path)


def test_paired_summary_excludes_quota_stops_but_includes_failed_complete_tasks():
    def row(case, condition, delivered):
        return {"id": case, "trial": 1, "condition": condition, "delivered": delivered,
                "observation_errors": [], "receipts": [{"usage": {"prompt_tokens": 100, "completion_tokens": 10}}]}
    report = {"fully_paired_cases": [[1, "complete"]], "input_output_usd_per_million": [0.3, 1.2],
              "cases": [row("complete", "fixed", False), row("complete", "adaptive", True), row("quota-stop", "fixed", False)]}
    summary = paired_summary(report)
    assert summary["fixed"]["calls"] == summary["adaptive"]["calls"] == 1
    assert summary["fixed"]["paired_cases"] == 1 and summary["fixed"]["delivered"] == 0
    assert summary["fixed"]["cost_per_delivered_usd"] is None
    assert summary["adaptive"]["cost_per_delivered_usd"] == pytest.approx(0.000042)
    assert summary["adaptive"]["cache_hit_tokens"] is None
