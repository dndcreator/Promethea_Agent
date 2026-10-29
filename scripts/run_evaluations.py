"""Versioned, budgeted, test-only behavior evaluation. No product-runtime hooks."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.evaluation import Budget, BudgetExceeded, calibration_ready, compare_behavior, digest, hard_checks, judge_matches_expectation, summarize, validate_judgment


ASSETS = ROOT / "tests/evaluation"


class Endpoint:
    def __init__(self, role, budget, output_tokens):
        from openai import AsyncOpenAI
        self.role, self.budget, self.output_tokens = role, budget, output_tokens
        prefix = "PROMETHEA_EVAL_" + role.upper() + "_"
        base, key, model = [os.environ.get(prefix + field) for field in ("BASE_URL", "API_KEY", "MODEL")]
        if not all((base, key, model)):
            raise ValueError(f"Explicit {prefix}BASE_URL/API_KEY/MODEL required; product credentials are never inherited")
        self.identity = {"model": model, "endpoint_hash": digest(base.rstrip("/"))}
        raw_rates = [os.environ.get(prefix + field + "_USD_PER_MILLION") for field in ("INPUT", "OUTPUT")]
        self.rates = tuple(float(value) for value in raw_rates) if all(value is not None for value in raw_rates) else None
        if self.rates is not None and any(not math.isfinite(value) or value < 0 for value in self.rates):
            raise ValueError("Evaluation prices must be finite, nonnegative text-token tariffs")
        if budget.max_cost_usd is not None and self.rates is None:
            raise ValueError("Currency budget requires explicit input/output prices for every model")
        self.client = AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=30)
        self.last_error = None
        self.usage = []

    async def call_llm(self, messages, **kwargs):
        self.last_error = None
        try:
            self.budget.admit(messages, self.output_tokens, self.rates)
            result = await asyncio.wait_for(self.client.chat.completions.create(
                model=self.identity["model"], messages=messages, temperature=0,
                max_tokens=self.output_tokens), timeout=min(30, self.budget.remaining()))
            usage = result.usage.model_dump() if result.usage else None
            self.budget.settle(usage, self.rates)
            self.usage.append(usage)
            if not result.choices or result.choices[0].finish_reason == "length":
                raise ValueError("model response missing or output limit reached")
            content = result.choices[0].message.content or ""
            if not content.strip():
                raise ValueError("model response empty")
            return {"status": "success", "content": content, "usage": usage}
        except Exception as error:
            self.last_error = type(error).__name__
            if not isinstance(error, BudgetExceeded):
                self.budget.usage_known = False
            if isinstance(error, BudgetExceeded):
                raise
            raise RuntimeError("Evaluation provider failure: " + self.last_error) from None

    def cost(self):
        rates = self.rates
        if rates is None or any(usage is None for usage in self.usage):
            return None
        # Operator-supplied flat text tariffs; not provider invoices/cache tariffs.
        return sum((usage["prompt_tokens"] * float(rates[0]) + usage["completion_tokens"] * float(rates[1])) / 1_000_000 for usage in self.usage)


async def judge_case(judge, rubric, case, evidence):
    dimensions = case.get("rubric", case.get("dimensions", []))
    payload = {"task": case.get("turns", case.get("task", case.get("user"))),
               "dimensions": {key: rubric["dimensions"][key] for key in dimensions},
               "response": evidence.get("answer", evidence.get("candidates")),
               "evidence": evidence["evidence"], "output": rubric["output"]}
    result = await judge.call_llm([{"role": "system", "content": rubric["instructions"]}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    return validate_judgment(json.loads(result["content"]), dimensions, evidence["evidence"])


async def calibrate(judge, rubric, dataset):
    policy = rubric["calibration_policy"]
    if not calibration_ready(dataset["cases"], policy["minimum_reviewed_cases"]):
        raise ValueError("Judge calibration requires reviewed task/behavior labels; current engineering labels do not qualify")
    results = []
    for case in dataset["cases"]:
        if not case.get("reviewed_by") or not case.get("reviewed_at"):
            continue
        votes = []
        for _ in range(3):
            verdict = await judge_case(judge, rubric, case, {"answer": case["answer"], "evidence": case["evidence"]})
            votes.append({key: verdict[key] for key in ("task_outcome", "behavior", "incomplete_reason")})
        results.append({"id": case["id"], "expected": case["expected"], "votes": votes})
    total = sum(len(row["votes"]) for row in results)
    accuracy = sum(vote == row["expected"] for row in results for vote in row["votes"]) / total
    agreement = sum(all(vote == row["votes"][0] for vote in row["votes"]) for row in results) / len(results)
    false_pass = sum(row["expected"]["behavior"] == "incorrect" and vote["behavior"] == "correct" for row in results for vote in row["votes"])
    false_completion = sum(row["expected"]["task_outcome"] != "completed" and vote["task_outcome"] == "completed" for row in results for vote in row["votes"])
    confusion = {axis: {label: {vote: 0 for vote in labels} for label in labels} for axis, labels in {
        "task_outcome": ("completed", "incomplete", "unverifiable"), "behavior": ("correct", "incorrect", "insufficient_evidence")}.items()}
    for row in results:
        for vote in row["votes"]:
            for axis in confusion:
                confusion[axis][row["expected"][axis]][vote[axis]] += 1
    return {"qualified": accuracy >= policy["minimum_accuracy"] and agreement >= policy["minimum_repeat_agreement"] and false_pass == 0 and false_completion == 0,
            "accuracy": accuracy, "repeat_agreement": agreement, "false_passes": false_pass,
            "false_completions": false_completion, "confusion_matrix": confusion,
            "rows": results}


def validate_assets(corpus, rubric):
    ids = [case["id"] for case in corpus["cases"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("Behavior case IDs must be nonempty and unique")
    for case in corpus["cases"]:
        if case["kind"] not in {"action", "classification", "retrieval", "ambient", "situation"} or case["category"] not in {"positive", "negative", "boundary", "historical_failure"}:
            raise ValueError("Unsupported case kind/category")
        if not set(case.get("rubric", [])).issubset(rubric["dimensions"]):
            raise ValueError("Unknown rubric dimension")
        if not case.get("expect"):
            raise ValueError("Each case needs observable checks")
        expected = case.get("judge_expect", {})
        allowed = {"task_outcome": {"completed", "incomplete", "unverifiable"}, "behavior": {"correct", "incorrect", "insufficient_evidence"}}
        if set(expected) - set(allowed) or any(not isinstance(values, list) or not values or not set(values) <= allowed[axis] for axis, values in expected.items()):
            raise ValueError("Invalid case-specific Judge expectations")


async def run(args):
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    rubric = json.loads((ASSETS / "judge.json").read_text(encoding="utf-8"))
    calibration = json.loads((ASSETS / "judge-calibration.json").read_text(encoding="utf-8"))
    validate_assets(corpus, rubric)
    cases = [case for case in corpus["cases"] if not args.group or case["group"] == args.group]
    if not cases:
        raise ValueError("No cases selected")
    if args.mode == "validate":
        return {"mode": "validate", "case_count": len(cases), "model_api_calls": 0, "quality_measured": False,
                "judge_labels_human_reviewed": calibration_ready(calibration["cases"]), "judge_calibrated": False}
    if args.judge and not calibration_ready(calibration["cases"]):
        raise ValueError("Review judge-calibration.json before any model call; --judge is fail-closed")
    budget = Budget(max_calls=args.max_calls, max_tokens=args.max_tokens, seconds=args.deadline, max_cost_usd=args.max_cost_usd)
    agent = judge = None
    try:
        agent = Endpoint("agent", budget, args.max_output_tokens) if args.mode == "live" and any(case["kind"] != "retrieval" for case in cases) else None
        judge = Endpoint("judge", budget, args.max_output_tokens) if args.judge else None
        if judge and agent and judge.identity == agent.identity:
            raise ValueError("Judge must use an independent model/endpoint, not the tested agent")
    except Exception:
        for endpoint in (agent, judge):
            if endpoint:
                await endpoint.client.close()
        raise
    report = {"version": 2, "mode": args.mode, "started_at": datetime.now(timezone.utc).isoformat(),
              "corpus_hash": digest(corpus), "rubric_hash": digest(rubric), "calibration_hash": digest(calibration),
              "case_ids": [case["id"] for case in cases], "repeat": args.repeat,
              "agent": agent.identity if agent else None, "judge": judge.identity if judge else None,
              "rows": [], "budgets": {"calls": args.max_calls, "tokens": args.max_tokens, "seconds": args.deadline, "cost_usd": args.max_cost_usd}}
    report["code_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source = {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8-sig") for folder in ("gateway", "memory", "computer", "core", "agentkit", "channels", "tests/support") for path in (ROOT / folder).rglob("*.py")}
    for name in ("conversation_core.py", "config.py"):
        source[name] = (ROOT / name).read_text(encoding="utf-8-sig")
    report["source_hash"] = digest(source)
    try:
        if judge:
            report["calibration"] = await calibrate(judge, rubric, calibration)
            if not report["calibration"]["qualified"]:
                raise ValueError("Judge failed calibration; behavior scores withheld")
        if args.mode == "replay":
            if not args.records:
                raise ValueError("--records live report required for replay")
            source = json.loads(args.records.read_text(encoding="utf-8"))
            if source["corpus_hash"] != digest(corpus) or source["rubric_hash"] != digest(rubric):
                raise ValueError("Replay corpus/rubric changed")
            inputs = [(next(case for case in cases if case["id"] == row["case_id"]), row["evidence"], row["trial"]) for row in source["rows"] if row["case_id"] in report["case_ids"] and "evidence" in row]
            if not inputs:
                raise ValueError("Replay has no matching evidence")
            expected = {(case["id"], trial + 1) for case in cases for trial in range(args.repeat)}
            actual = {(case["id"], trial) for case, _, trial in inputs}
            if actual != expected or len(inputs) != len(expected):
                raise ValueError("Replay requires every selected case/trial exactly once")
            report["replayed_source_hash"] = source.get("source_hash")
        else:
            inputs = [(case, None, trial + 1) for case in cases for trial in range(args.repeat)]
        failures = 0
        for case, evidence, trial in inputs:
            started = time.monotonic()
            row = {"case_id": case["id"], "group": case["group"], "trial": trial}
            try:
                if evidence is None:
                    from tests.support.behavior import execute_case
                    with tempfile.TemporaryDirectory(prefix="case-", dir=args.output) as temporary:
                        evidence = await asyncio.wait_for(execute_case(case, agent, Path(temporary)), timeout=min(60, budget.remaining()))
                errors = hard_checks(case, evidence)
                row.update(evidence=evidence, hard_pass=not errors, failures=errors)
                if judge and case.get("rubric"):
                    row["judge"] = await judge_case(judge, rubric, case, evidence)
                    row["judge_expectation_met"] = judge_matches_expectation(case, row["judge"])
                row["semantic_status"] = "measured" if "judge" in row else "not_measured" if case.get("rubric") else "not_required"
                failures += bool(errors) or row.get("judge_expectation_met") is False
            except Exception as error:
                row.setdefault("hard_pass", False)
                row.setdefault("failures", [])
                row.update(evaluation_error=type(error).__name__, error=str(error)[:1000], semantic_status="evaluation_error")
                failures += 1
                if isinstance(error, BudgetExceeded) or not budget.usage_known:
                    report["stop_reason"] = "budget_or_provider_failure"
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            report["rows"].append(row)
            if not budget.usage_known:
                report["stop_reason"] = "provider_usage_unavailable"
            if report.get("stop_reason") or failures >= args.max_failures or budget.remaining() <= 0:
                report.setdefault("stop_reason", "failure_or_time_limit")
                break
    finally:
        report["model_api_calls"], report["known_tokens"] = budget.calls, budget.tokens
        report["usage_known"] = budget.usage_known
        report["estimated_cost_usd"] = None if not budget.usage_known or any(endpoint.cost() is None for endpoint in (agent, judge) if endpoint) else sum(endpoint.cost() for endpoint in (agent, judge) if endpoint)
        report["groups"] = summarize(report["rows"])
        report["cases"] = {case_id: {"trials": len(rows), "hard_passes": sum(row.get("hard_pass") is True for row in rows),
                                    "failure_types": sorted({failure for row in rows for failure in row.get("failures", [])} |
                                                            {"evaluation:" + row["evaluation_error"] for row in rows if row.get("evaluation_error")})}
                           for case_id in report["case_ids"] if (rows := [row for row in report["rows"] if row["case_id"] == case_id])}
        report["completed_trials"] = len(report["rows"])
        report["planned_trials"] = len(cases) * args.repeat
        report["quality_measured"] = bool(judge and report.get("calibration", {}).get("qualified") and any(row.get("judge") for row in report["rows"]))
        for endpoint in (agent, judge):
            if endpoint:
                await endpoint.client.close()
        (args.output / "behavior.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.compare:
            report["comparison"] = compare_behavior(json.loads(args.compare.read_text(encoding="utf-8")), report)
        (args.output / "behavior.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["validate", "live", "replay"], default="validate")
    parser.add_argument("--group")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--records", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--max-cost-usd", type=float, help="requires explicit evaluation token tariffs; never guessed")
    parser.add_argument("--max-output-tokens", type=int, default=800)
    parser.add_argument("--deadline", type=int, default=180)
    parser.add_argument("--max-failures", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.max_calls, args.max_tokens, args.max_output_tokens, args.deadline, args.max_failures) <= 0:
        parser.error("All budgets must be positive")
    if args.max_cost_usd is not None and (not math.isfinite(args.max_cost_usd) or args.max_cost_usd <= 0):
        parser.error("Currency budget must be finite and positive")
    args.output = args.output or ROOT / ".tmp/evaluations" / ("behavior-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.isolated_worker and (ROOT.name != "code" or not ROOT.parent.name.startswith("isolation-")):
        parser.error("Evaluation worker requires a disposable source snapshot")
    if args.mode == "live" and not args.isolated_worker:
        from tests.support.snapshot import copy_code
        from tests.support.process import run_bounded
        with tempfile.TemporaryDirectory(prefix="isolation-", dir=args.output) as temporary:
            code = Path(temporary) / "code"
            code.mkdir()
            copy_code(code)
            (code / "scripts").mkdir()
            shutil.copyfile(Path(__file__), code / "scripts/run_evaluations.py")
            shutil.copytree(ASSETS, code / "tests/evaluation")
            env = {key: value for key, value in os.environ.items() if "__" not in key}
            env.update(MEMORY__ENABLED="false", MEMORY__NEO4J__ENABLED="false", SELF_EVOLVE__ENABLED="false")
            command = [sys.executable, str(code / "scripts/run_evaluations.py"), *sys.argv[1:], "--output", str(args.output), "--isolated-worker"]
            if args.records:
                command += ["--records", str(args.records.resolve())]
            if args.compare:
                command += ["--compare", str(args.compare.resolve())]
            try:
                return run_bounded(command, cwd=code, env=env, timeout=args.deadline + 30)
            except subprocess.TimeoutExpired:
                print("Evaluation worker exceeded its wall-clock budget", file=sys.stderr)
                return 1
    try:
        report = asyncio.run(run(args))
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in report.items() if key not in {"rows", "comparison"}}, indent=2))
    return int(bool(report.get("stop_reason")) or any(row.get("evaluation_error") or not row["hard_pass"] or row.get("judge_expectation_met") is False for row in report.get("rows", [])))


if __name__ == "__main__":
    raise SystemExit(main())
