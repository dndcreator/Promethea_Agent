"""Compare task delivery, not text length, using the existing isolated Runtime."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support.evaluation import Budget, digest, journal_exposure


def audit_previous(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    comparable = {tuple(group) for group in report["fully_paired_cases"]}
    rows = []
    for row in report["cases"]:
        event_path = path.parent / f'trial-{row["trial"]}' / row["id"] / row["condition"] / "events.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()] if event_path.is_file() else []
        observed = [event["payload"] for event in events if event["event_type"] == "action.observation.committed"]
        writes = [event for event in observed if event.get("tool_name") == "workspace.write_file" and event.get("ok")]
        steps = {event["payload"].get("model_step_id"): index for index, event in enumerate(
            [event for event in events if event["event_type"] == "model.call.recorded"], 1)}
        write_calls = [steps[event["model_step_id"]] for event in writes if event.get("model_step_id") in steps]
        files = path.parent / f'trial-{row["trial"]}' / row["id"] / row["condition"] / "workspaces/alice/evaluation"
        code_files = [{"path": file.name, "bytes": file.stat().st_size, "hash": digest(file.read_text(encoding="utf-8")),
                       "matches_original_receipt": digest(file.read_text(encoding="utf-8")) == row["artifact_hashes"].get(file.name)}
                      for file in sorted(files.glob("*.html"))] if files.is_dir() else []
        rows.append({"id": row["id"], "trial": row["trial"], "condition": row["condition"], "comparable": (row["trial"], row["id"]) in comparable,
                     "delivered_under_original_checks": row["delivered"], "calls": row["calls"],
                     "protocol_errors": row["observation_errors"].count("INVALID_MODEL_ACTION"),
                     "output_truncations": row["observation_errors"].count("MODEL_OUTPUT_LIMIT"),
                     "successful_write_observations": len(writes), "successful_write_calls": write_calls,
                     "first_successful_write_call": min(write_calls) if write_calls else None,
                     "calls_after_last_successful_write": row["calls"] - max(write_calls) if write_calls else None,
                     "retained_code_artifacts": code_files})
    return {"mode": "previous_evidence_audit", "new_paid_calls": 0, "source": str(path), "rows": rows,
            "limits": "Historical intermediate artifact versions were not captured. Do not invent check-by-check progress or measure old tasks against new requirements. Code bytes are evidence of files, not quality."}


def experiment_schedule(corpus, repeat, seed):
    rng = random.Random(seed)
    schedule = []
    for trial in range(1, repeat + 1):
        cases = list(corpus["cases"])
        rng.shuffle(cases)
        for case in cases:
            policies = list(corpus["policies"])
            rng.shuffle(policies)
            schedule.extend({"trial": trial, "case_id": case["id"], "policy_id": policy["id"]} for policy in policies)
    return schedule


def source_fingerprint():
    paths = list(ROOT.glob("*.py"))
    for folder in ("gateway", "core", "computer", "agentkit", "memory", "channels", "skills", "brain", "utils", "scripts", "tests/support"):
        paths.extend((ROOT / folder).rglob("*.py"))
    return digest({str(path.relative_to(ROOT)): digest(path.read_bytes().hex()) for path in sorted(paths)})


def prior_exposure(path, *, identity, rates, input_token_cap):
    if path is None:
        return {"known_usd": 0, "unknown_reserve_usd": 0, "total_usd": 0, "calls": 0, "known_tokens": 0}
    previous = json.loads(path.read_text(encoding="utf-8"))
    if previous["endpoint"] != identity or tuple(previous["input_output_usd_per_million"]) != tuple(rates):
        raise ValueError("prior exposure must use the same endpoint/model and conservative rates")
    if previous.get("prior_exposure", {}).get("calls"):
        raise ValueError("nested restart ledgers are not supported")
    known, reserve, known_tokens, unknown = 0.0, 0.0, 0, 0
    receipts = [receipt for row in previous["cases"] for receipt in row["receipts"]]
    for receipt in receipts:
        usage = receipt.get("usage")
        if usage is not None:
            known += (usage["prompt_tokens"] * rates[0] + usage["completion_tokens"] * rates[1]) / 1_000_000
            known_tokens += usage["prompt_tokens"] + usage["completion_tokens"]
        else:
            unknown += 1
            bound = receipt.get("input_bytes")
            if bound is None:
                if not input_token_cap or input_token_cap <= 0:
                    raise ValueError("legacy unreceipted requests require an explicit provider input-token ceiling")
                bound = input_token_cap
            else:
                bound += receipt["max_tokens"] + 512
            reserve += (bound * rates[0] + receipt["max_tokens"] * rates[1]) / 1_000_000
    return {"report_hash": digest(previous), "known_usd": known, "unknown_reserve_usd": reserve,
            "total_usd": known + reserve, "calls": len(receipts), "known_tokens": known_tokens,
            "unknown_requests": unknown, "legacy_input_token_cap": input_token_cap,
            "limits": "Unreceipted requests reserve the full admitted byte-based bound, or the explicitly supplied provider context ceiling for legacy records. This is a conservative exposure assumption, not an invoice."}


async def run_live(output, env_file, max_cost, repeat, corpus_path=None, seed=20261031, request_timeout=30, prior_run=None, unknown_input_token_cap=None, max_request_cost=None, shared_budget=None, case_runner=None):
    from tests.support.runtime_efficiency import eval_settings, PairedEndpoint, live_case
    from tests.support.task_progress import browser_checks, summarize_policies, resolve_output_policy, summarize_categories
    case_runner = case_runner or live_case

    if not math.isfinite(max_cost) or max_cost <= 0:
        raise ValueError("explicit positive experiment budget required")
    if max_request_cost is not None and (not math.isfinite(max_request_cost) or max_request_cost <= 0):
        raise ValueError("positive finite request reserve required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("use a fresh output directory to preserve previous evidence")
    corpus = json.loads((corpus_path or ROOT / "tests/evaluation/task-progress-live.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in corpus["cases"]}
    policies = {policy["id"]: policy for policy in corpus["policies"]}
    resolved = {(case["id"], policy["id"]): resolve_output_policy(policy, case, corpus.get("prediction"))
                for case in corpus["cases"] for policy in corpus["policies"]}
    schedule = experiment_schedule(corpus, repeat, seed)
    values, _, rates = eval_settings(env_file)
    identity = {"model": values["PROMETHEA_EVAL_AGENT_MODEL"], "endpoint_hash": digest(values["PROMETHEA_EVAL_AGENT_BASE_URL"])}
    exposure = prior_exposure(prior_run, identity=identity, rates=rates, input_token_cap=unknown_input_token_cap)
    if shared_budget is not None:
        if prior_run is not None or shared_budget.max_cost_usd != max_cost or not shared_budget.usage_known:
            raise ValueError("shared admission ledger must be known, match the ceiling, and have no restart ledger")
        exposure = {"known_usd": shared_budget.cost_usd, "unknown_reserve_usd": 0, "total_usd": shared_budget.cost_usd,
                    "calls": shared_budget.calls, "known_tokens": shared_budget.tokens, "source": "shared_admission_ledger"}
    if exposure["total_usd"] >= max_cost:
        raise ValueError("prior spending/reserves exhaust the original currency ceiling")
    canary = await browser_checks('<output id="ready">ready</output>', [{"id": "ready", "assertions": [{"selector": "#ready", "text": "ready"}]}])
    if not canary["ready"]["passed"]:
        raise RuntimeError("browser evaluator canary failed; no paid calls allowed")
    budget = shared_budget if shared_budget is not None else Budget(max_calls=180, max_tokens=1200000, seconds=1800, max_cost_usd=max_cost)
    budget.cost_usd, budget.calls, budget.tokens = exposure["total_usd"], exposure["calls"], exposure["known_tokens"]
    endpoint = PairedEndpoint(values, budget, rates, request_timeout=request_timeout, journal_path=output / "requests.jsonl", max_request_cost_usd=max_request_cost)
    output.mkdir(parents=True, exist_ok=True)
    source_hash = source_fingerprint()
    (output / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "plan.json").write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_hash": digest(corpus), "source_hash": source_hash, "budget_usd": max_cost,
        "rates": rates, "seed": seed, "schedule": schedule, "request_timeout": request_timeout, "max_request_cost_usd": max_request_cost, "prior_exposure": exposure,
        "resolved_policies": [{"case_id": case_id, "policy_id": policy_id, **value} for (case_id, policy_id), value in resolved.items()]}, ensure_ascii=False, indent=2), encoding="utf-8")
    rows, stop = [], None
    try:
        for entry in schedule:
            case, policy = cases[entry["case_id"]], policies[entry["policy_id"]]
            effective = resolved[(case["id"], policy["id"])]
            before, cost = len(endpoint.receipts), budget.cost_usd
            root = output / f'trial-{entry["trial"]}' / case["id"] / policy["id"]
            root.mkdir(parents=True)
            try:
                row = await case_runner(case, endpoint, root, policy["id"], policy={**effective, "max_steps": corpus["max_steps"]})
                complete = budget.usage_known and not endpoint.stop_reason and not row["progress"]["evaluation_errors"]
            except Exception as exc:
                row = {"id": case["id"], "condition": policy["id"], "delivered": False, "progress": None, "evaluator_error": type(exc).__name__}
                complete = False
            row.update(trial=entry["trial"], category=case.get("category"), evaluation_complete=complete, calls=len(endpoint.receipts) - before,
                       effective_policy=effective,
                       conservative_cost_usd=budget.cost_usd - cost if budget.usage_known else None,
                       receipts=deepcopy(endpoint.receipts[before:]))
            rows.append(row)
            (output / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            if not complete:
                stop = endpoint.stop_reason or "unknown billing or evaluator failure"
                break
    finally:
        await endpoint.client.close()
    journal = journal_exposure(output / "requests.jsonl")
    report = {"version": 1, "mode": "three_arm_budget_prediction" if corpus.get("prediction") else "three_arm_task_progress", "corpus_hash": digest(corpus), "endpoint": endpoint.identity,
              "source_hash": source_hash,
              "repeat": repeat, "policies": corpus["policies"], "prediction": corpus.get("prediction"), "seed": seed, "schedule": schedule, "max_steps": corpus["max_steps"],
              "input_output_usd_per_million": rates, "budget_usd": max_cost, "model_api_calls": len(endpoint.receipts),
              "total_model_api_calls_including_prior": budget.calls, "prior_exposure": exposure, "request_timeout": request_timeout,
              "current_known_cost_usd": budget.cost_usd - exposure["total_usd"] if budget.usage_known else None,
              "overall_usage_known": budget.usage_known and not exposure.get("unknown_requests"),
              "conservative_cost_usd": budget.cost_usd if budget.usage_known else None, "usage_known": budget.usage_known,
              "stop_reason": stop, "cases": rows, "summary": summarize_policies(rows, corpus["policies"]),
              "by_category": summarize_categories(rows, corpus["policies"]), "request_journal": journal,
              "admission_exposure_usd": budget.cost_usd + journal["unknown_reserve_usd"],
              "limits": "All arms share current Runtime, recovery limits, tools, observations and step cap; only initial/ceiling output allowance differs. Prediction uses a declared contract shared with all arms, not semantic inference from arbitrary chat or unknown future actions. No per-step predictor is tested. Check snapshots are evaluator-only and never help the Agent. Browser checks are isolated and network-blocked; no production Canvas mounting or cross-restart/longitudinal result is claimed. More reasoning/text is not scored. Small repeated smoke sample, not statistical proof."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--previous", type=Path)
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.eval")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--repeat", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--corpus", type=Path, default=ROOT / "tests/evaluation/task-progress-live.json")
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--request-timeout", type=int, choices=range(30, 181), default=30)
    parser.add_argument("--max-request-cost-usd", type=float)
    parser.add_argument("--prior-run", type=Path)
    parser.add_argument("--unknown-input-token-cap", type=int)
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.previous:
        report = audit_previous(args.previous)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"new_paid_calls": 0, "cases": len(report["rows"])}))
    else:
        if args.max_cost_usd is None:
            parser.error("--live requires an explicitly authorized --max-cost-usd")
        corpus_path = args.corpus.resolve()
        if not corpus_path.is_relative_to(ROOT / "tests/evaluation") or corpus_path.suffix != ".json":
            parser.error("experiment corpus must be a JSON file inside tests/evaluation")
        if args.isolated_worker and (ROOT.name != "code" or not ROOT.parent.name.startswith("isolation-")):
            parser.error("worker requires an isolated source snapshot")
        if not args.isolated_worker:
            from tests.support.snapshot import copy_production_code
            from tests.support.production import environment
            from tests.support.process import run_bounded
            output = args.output.resolve()
            if not output.is_relative_to(ROOT / ".tmp/evaluations"):
                parser.error("live output must stay inside .tmp/evaluations")
            if args.prior_run and not args.prior_run.resolve().is_relative_to(ROOT / ".tmp/evaluations"):
                parser.error("prior experiment must stay inside .tmp/evaluations")
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="isolation-", dir=output.parent) as temporary:
                code = Path(temporary) / "code"
                code.mkdir()
                copy_production_code(code)
                (code / "scripts").mkdir(exist_ok=True)
                shutil.copyfile(Path(__file__), code / "scripts/evaluate_task_progress.py")
                (code / "tests/evaluation").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(corpus_path, code / "tests/evaluation" / corpus_path.name)
                env = environment(code)
                env.update(MEMORY__ENABLED="false", MEMORY__NEO4J__ENABLED="false", SELF_EVOLVE__ENABLED="false")
                for key in ("CANVAS_TEST_BROWSER_CHANNEL", "PLAYWRIGHT_BROWSERS_PATH"):
                    if os.environ.get(key):
                        env[key] = os.environ[key]
                command = [sys.executable, str(code / "scripts/evaluate_task_progress.py"), "--live", "--isolated-worker",
                           "--env-file", str(args.env_file.resolve()), "--output", str(output),
                           "--repeat", str(args.repeat), "--max-cost-usd", str(args.max_cost_usd),
                           "--corpus", str(code / "tests/evaluation" / corpus_path.name), "--seed", str(args.seed),
                           "--request-timeout", str(args.request_timeout)]
                if args.max_request_cost_usd is not None:
                    command += ["--max-request-cost-usd", str(args.max_request_cost_usd)]
                if args.prior_run:
                    command += ["--prior-run", str(args.prior_run.resolve())]
                if args.unknown_input_token_cap is not None:
                    command += ["--unknown-input-token-cap", str(args.unknown_input_token_cap)]
                raise SystemExit(run_bounded(command, cwd=code, env=env, timeout=1860))
        report = asyncio.run(run_live(args.output.resolve(), args.env_file, args.max_cost_usd, args.repeat, args.corpus, args.seed,
                                     args.request_timeout, args.prior_run, args.unknown_input_token_cap, args.max_request_cost_usd))
        print(json.dumps({key: report[key] for key in ("model_api_calls", "conservative_cost_usd", "stop_reason", "summary")}, ensure_ascii=False))
