import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts.audit_test_assets import inventory
from scripts.run_evaluations import ASSETS, run, validate_assets
from tests.support.evaluation import Budget, BudgetExceeded, calibration_ready, compare_behavior, hard_checks, summarize, validate_judgment


def test_asset_registry_has_unique_existing_targets_and_no_shadowed_test_copies():
    root = Path(__file__).resolve().parents[1]
    suites = json.loads((ASSETS / "suites.json").read_text())
    for name, paths in suites.items():
        if name == "version":
            continue
        assert len(paths) == len(set(paths)), name
        assert all((root / path).is_file() for path in paths), name
    report = inventory(root)
    assert report["exact_duplicate_candidates"] == []


def test_behavior_corpus_has_distinct_ids_risks_and_observable_expectations():
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    rubric = json.loads((ASSETS / "judge.json").read_text(encoding="utf-8"))
    validate_assets(corpus, rubric)
    assert {case["category"] for case in corpus["cases"]} == {"positive", "negative", "boundary", "historical_failure"}
    assert {"action", "memory", "retrieval", "situation", "ambient", "continuity"} <= {case["group"] for case in corpus["cases"]}
    broken = deepcopy(corpus)
    broken["cases"].append(broken["cases"][0])
    with pytest.raises(ValueError, match="unique"):
        validate_assets(broken, rubric)


def test_budget_consumes_failed_admissions_and_stops_unknown_usage():
    budget = Budget(max_calls=1, max_tokens=2000)
    budget.admit([{"role": "user", "content": "test"}], 50)
    budget.settle({"prompt_tokens": 10, "completion_tokens": 2})
    assert budget.tokens == 12
    with pytest.raises(BudgetExceeded):
        budget.admit([], 1)
    budget = Budget()
    budget.settle(None)
    with pytest.raises(BudgetExceeded):
        budget.admit([], 1)
    with pytest.raises(BudgetExceeded):
        Budget(seconds=0).admit([], 1)
    with pytest.raises(BudgetExceeded):
        Budget(max_tokens=10).admit([], 50)
    with pytest.raises(BudgetExceeded):
        Budget(max_cost_usd=1).admit([], 50)
    priced = Budget(max_cost_usd=0.00001)
    with pytest.raises(BudgetExceeded):
        priced.admit([], 100, rates=(1, 1))


def test_real_artifact_failure_cannot_be_overruled_by_success_message_or_judge():
    case = {"kind": "action", "expect": {"required_tools": ["workspace.write_file"], "artifacts": {"result.txt": "NET=32"}}}
    claimed = {"status": "success", "answer": "Done!", "tools": ["workspace.write_file"], "artifacts": {}}
    assert hard_checks(case, claimed) == ["artifact_mismatch:result.txt"]
    claimed["artifacts"]["result.txt"] = "NET=23"
    assert hard_checks(case, claimed) == ["artifact_mismatch:result.txt"]
    claimed["artifacts"]["result.txt"] = "NET=32"
    assert hard_checks(case, claimed) == []


@pytest.mark.parametrize("mutation", ["bad_ref", "contradiction", "missing_dimension", "unknown_verdict"])
def test_judge_invalid_or_invented_evidence_is_not_a_score(mutation):
    value = {"task_outcome": "completed", "behavior": "correct", "incomplete_reason": "none", "reason_evidence_ids": [], "dimensions": {"grounding": "pass"}, "evidence_ids": ["file:1"], "reason": "Matches the file"}
    assert validate_judgment(value, ["grounding"], {"file:1"}) == value
    if mutation == "bad_ref":
        value["evidence_ids"] = ["invented"]
    elif mutation == "contradiction":
        value["behavior"] = "incorrect"
    elif mutation == "missing_dimension":
        value["dimensions"] = {}
    else:
        value["dimensions"]["grounding"] = "probably"
    with pytest.raises(ValueError):
        validate_judgment(value, ["grounding"], {"file:1"})


def test_incomplete_honest_behavior_is_not_task_success_or_behavior_failure():
    from tests.support.evaluation import judge_matches_expectation
    data = json.loads((ASSETS / "judge-calibration.json").read_text())
    case = next(case for case in data["cases"] if case["id"] == "runtime-unavailable-honest-boundary")
    result = {**case["expected"], "dimensions": case["expected_dimensions"], "evidence_ids": list(case["evidence"]),
              "reason_evidence_ids": ["runtime:capabilities"], "reason": "Unavailable in the Runtime snapshot"}
    assert validate_judgment(result, case["dimensions"], case["evidence"])["behavior"] == "correct"
    summary = summarize([{"group": "capability", "hard_pass": True, "judge": result}])["capability"]
    assert summary["task_outcomes"]["completed"] == 0
    assert summary["task_outcomes"]["incomplete"] == 1
    assert summary["behavior_judgments"]["correct"] == 1
    assert not judge_matches_expectation({}, result)
    assert judge_matches_expectation({"judge_expect": {"task_outcome": ["incomplete"], "behavior": ["correct"]}}, result)
    for refs, catalog in [([], case["evidence"]), (["answer"], {"answer": "I cannot see"})]:
        result["reason_evidence_ids"] = refs
        result["evidence_ids"] = list(catalog)
        with pytest.raises(ValueError, match="Runtime"):
            validate_judgment(result, case["dimensions"], catalog)


def test_missing_observation_alone_does_not_prove_capability_absence():
    value = {"task_outcome": "unverifiable", "behavior": "insufficient_evidence", "incomplete_reason": "unknown",
             "reason_evidence_ids": [], "dimensions": {"grounding": "uncertain"}, "evidence_ids": [], "reason": "No Runtime evidence"}
    assert validate_judgment(value, ["grounding"], {}) == value
    value["incomplete_reason"] = "capability_unavailable"
    with pytest.raises(ValueError, match="Runtime evidence"):
        validate_judgment(value, ["grounding"], {})


@pytest.mark.asyncio
async def test_uncalibrated_judge_is_blocked_before_any_model_api(monkeypatch, tmp_path):
    calibration = json.loads((ASSETS / "judge-calibration.json").read_text())
    assert calibration_ready(calibration["cases"])
    for case in calibration["cases"]:
        case["reviewed_by"] = None
        case["reviewed_at"] = None
    assert not calibration_ready(calibration["cases"])
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("behavior.json", "judge.json"):
        shutil.copy2(ASSETS / name, assets / name)
    (assets / "judge-calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    monkeypatch.setattr("scripts.run_evaluations.ASSETS", assets)

    def forbidden(*args):
        raise AssertionError("No API client may be constructed")

    monkeypatch.setattr("scripts.run_evaluations.Endpoint", forbidden)
    with pytest.raises(ValueError, match="before any model call"):
        await run(SimpleNamespace(mode="live", group=None, judge=True, output=tmp_path))


def test_comparison_refuses_changed_or_incomplete_runs_and_reports_uncertainty():
    before = {"mode": "live", "corpus_hash": "a", "rubric_hash": "b", "case_ids": ["c"], "repeat": 3,
              "completed_trials": 3, "planned_trials": 3, "groups": {"action": {"hard_pass_rate": 1}}}
    assert compare_behavior(before, deepcopy(before))["action"]["before"] == before["groups"]["action"]
    changed = deepcopy(before)
    changed["corpus_hash"] = "new"
    with pytest.raises(ValueError, match="Incompatible"):
        compare_behavior(before, changed)
    changed = deepcopy(before)
    changed["completed_trials"] = 2
    with pytest.raises(ValueError, match="Incomplete"):
        compare_behavior(before, changed)
    result = summarize([{"group": "action", "hard_pass": True}, {"group": "action", "hard_pass": False}])["action"]
    assert result["hard_pass_rate"] == 0.5
    assert result["wilson95"][0] < 0.5 < result["wilson95"][1]


@pytest.mark.asyncio
async def test_free_retrieval_cases_use_real_store_in_an_isolated_directory(tmp_path):
    from tests.support.behavior import execute_case
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    for index, case in enumerate(corpus["cases"]):
        if case["kind"] == "retrieval":
            root = tmp_path / str(index)
            root.mkdir()
            facts = await execute_case(case, None, root)
            assert hard_checks(case, facts) == [], (case["id"], facts)


@pytest.mark.asyncio
async def test_invalid_model_output_cannot_pass_as_safe_empty_memory(tmp_path):
    from tests.support.behavior import execute_case

    class BadModel:
        last_error = None

        async def call_llm(self, *args):
            return {"content": "malformed JSON"}

    case = {"kind": "classification", "user": "Imagine a villa on Mars", "assistant": "A story", "expect": {"no_candidates": True}}
    with pytest.raises(RuntimeError, match="Invalid memory model contract"):
        await execute_case(case, BadModel(), tmp_path)


@pytest.mark.asyncio
async def test_situation_observations_reach_real_prompt_and_closed_views_do_not_claim_presence(tmp_path):
    from tests.support.behavior import execute_case
    from tests.support.runtime import ScriptedModel
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    for name in ("situation-visible-content", "situation-closed-view"):
        case = next(case for case in corpus["cases"] if case["id"] == name)
        root = tmp_path / name
        root.mkdir()
        model = ScriptedModel([{"action": "answer", "content": "41"}])
        facts = await execute_case(case, model, root)
        assert any(key.startswith("runtime:capabilities:") for key in facts["evidence"])
        rendered = json.dumps(model.calls[0], ensure_ascii=False)
        if not case.get("closed"):
            assert "Current quote" in rendered and "41" in rendered
        else:
            assert not facts["evidence"]["environment"]["objects"]


@pytest.mark.asyncio
async def test_deadline_really_cancels_work_not_just_marks_a_report():
    cancelled = asyncio.Event()

    async def hung():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(hung(), timeout=0.01)
    assert cancelled.is_set()


def test_junit_reporting_distinguishes_known_debt_skip_and_actual_failure(tmp_path):
    from tests.support.reporting import read_junit, compare_runs
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite><testcase classname="a" name="pass" time="1"/>'
                    '<testcase classname="a" name="known"><skipped type="pytest.xfail"/></testcase>'
                    '<testcase classname="a" name="optional"><skipped/></testcase>'
                    '<testcase classname="b" name="broken"><failure message="wrong"/></testcase>'
                    '</testsuite></testsuites>', encoding="utf-8")
    report = read_junit(path)
    assert report["totals"] == {"passed": 1, "seconds": 1.0, "xfailed": 1, "skipped": 1, "failed": 1}
    assert report["failures"][0]["case"] == "b::broken"
    assert compare_runs({"modules": {}}, report)["b"]["new_failures"] == 1


def test_subprocess_timeout_stops_the_owned_process():
    import subprocess
    import sys
    from tests.support.process import run_bounded
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.asyncio
async def test_disabled_ambient_evaluation_never_constructs_a_model_call(tmp_path):
    from tests.support.behavior import execute_case
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    case = next(case for case in corpus["cases"] if case["kind"] == "ambient" and not case["enabled"])
    facts = await execute_case(case, None, tmp_path)
    assert hard_checks(case, facts) == []
    assert facts["model_calls"] == 0


@pytest.mark.asyncio
async def test_enabled_ambient_adapter_uses_actual_task_and_observation_results(tmp_path):
    from tests.support.behavior import execute_case
    from tests.support.runtime import ScriptedModel, finish_from_observation

    class CountedModel(ScriptedModel):
        def __init__(self):
            super().__init__([{"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "report.txt"}}, finish_from_observation])
            self.budget = SimpleNamespace(calls=0)

        async def call_llm(self, *args, **kwargs):
            self.budget.calls += 1
            return await super().call_llm(*args, **kwargs)

    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    case = next(case for case in corpus["cases"] if case["id"] == "ambient-investigate")
    facts = await execute_case(case, CountedModel(), tmp_path)
    assert hard_checks(case, facts) == [], facts
    assert "payment-17" in json.dumps(facts["evidence"], ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("false_pass", [False, True])
async def test_judge_calibration_repeats_labels_and_rejects_false_success(false_pass):
    from scripts.run_evaluations import calibrate
    dataset = json.loads((ASSETS / "judge-calibration.json").read_text())
    rubric = json.loads((ASSETS / "judge.json").read_text())

    class JudgeFixture:
        calls = 0

        async def call_llm(self, messages):
            case = dataset["cases"][self.calls // 3]
            self.calls += 1
            value = {**case["expected"], "dimensions": dict(case["expected_dimensions"]),
                     "reason_evidence_ids": list(case["evidence"]) if case["expected"]["incomplete_reason"] not in {"unknown", "none"} else [],
                     "evidence_ids": list(case["evidence"]), "reason": "Fixture judgment"}
            if false_pass and value["behavior"] == "incorrect":
                value["behavior"] = "correct"
                value["dimensions"]["grounding"] = "pass"
            return {"content": json.dumps(value)}

    judge = JudgeFixture()
    report = await calibrate(judge, rubric, dataset)
    assert judge.calls == len(dataset["cases"]) * 3
    if false_pass:
        assert not report["qualified"]
        assert report["false_passes"] == 3
        assert report["confusion_matrix"]["behavior"]["incorrect"]["correct"] == 3
    else:
        assert report["qualified"]
        assert report["confusion_matrix"]["behavior"]["incorrect"]["incorrect"] == 3


def test_source_snapshot_excludes_operator_configuration_and_runtime_data(monkeypatch, tmp_path):
    from tests.support import snapshot
    source, target = tmp_path / "source", tmp_path / "code"
    for folder in (source, target, source / "tests", source / "config", source / "memory"):
        folder.mkdir(exist_ok=True)
    for name, content in {"config.py": "# source", ".env": "SECRET=not-for-eval", "config/users.json": "personal", "memory/private.db": "private", "tests/__init__.py": ""}.items():
        (source / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(snapshot, "ROOT", source)
    snapshot.copy_code(target)
    assert (target / "config.py").is_file()
    assert not (target / ".env").exists()
    assert not (target / "config/users.json").exists()
    assert not (target / "memory/private.db").exists()
