"""Opt-in protocol pilot; never changes the product's model protocol."""
import argparse
import asyncio
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


async def run(output, env_file, maximum, request_cap, seed, prior_run=None):
    from tests.support.protocol_eval import NativeEndpoint, protocol_case
    from tests.support.runtime_efficiency import PairedEndpoint, eval_settings
    from scripts.evaluate_task_progress import source_fingerprint

    if any(not math.isfinite(value) or value <= 0 for value in (maximum, request_cap)):
        raise ValueError("explicit positive global/request budgets required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("use a fresh evidence directory")
    values, _, rates = eval_settings(env_file)
    prior = None
    if prior_run:
        prior = json.loads(prior_run.read_text(encoding="utf-8"))
        identity = {"model": values["PROMETHEA_EVAL_AGENT_MODEL"], "endpoint_hash": digest(values["PROMETHEA_EVAL_AGENT_BASE_URL"])}
        if prior["mode"] != "protocol_pilot" or prior["endpoint"] != identity or tuple(prior["rates"]) != tuple(rates) or not prior["usage_known"] or prior["unknown_reserve_usd"] or prior.get("prior_run"):
            raise ValueError("prior pilot must have complete matching usage and no nested ledger")
        if not 0 <= prior["known_conservative_cost_usd"] < maximum:
            raise ValueError("prior pilot already exhausts the original currency ceiling")
    corpus = json.loads((ROOT / "tests/evaluation/protocol-live.json").read_text(encoding="utf-8"))
    rng = random.Random(seed)
    cases, schedule = list(corpus["cases"]), []
    rng.shuffle(cases)
    for case in cases:
        modes = ["prompt_json", "native"]
        rng.shuffle(modes)
        schedule.extend({"id": case["id"], "mode": mode} for mode in modes)
    output.mkdir(parents=True)
    plan = {"corpus_hash": digest(corpus), "source_hash": source_fingerprint(), "budget_usd": maximum,
            "request_cap_usd": request_cap, "request_timeout": 120, "max_steps": 4, "output_tokens": 8192,
            "seed": seed, "schedule": schedule}
    plan["prior_run"] = {"report_hash": digest(prior), "known_cost_usd": prior["known_conservative_cost_usd"], "calls": prior["calls"]} if prior else None
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (output / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    budget, rows, stop = Budget(max_calls=100, max_tokens=1200000, seconds=1800, max_cost_usd=maximum), [], None
    if prior:
        budget.cost_usd, budget.calls = prior["known_conservative_cost_usd"], prior["calls"]
        budget.tokens = sum(receipt["usage"]["prompt_tokens"] + receipt["usage"]["completion_tokens"] for row in prior["cases"] for receipt in row["receipts"])
    lookup = {case["id"]: case for case in cases}
    for entry in schedule:
        root = output / entry["id"] / entry["mode"]
        root.mkdir(parents=True)
        constructor = NativeEndpoint if entry["mode"] == "native" else PairedEndpoint
        endpoint = constructor(values, budget, rates, request_timeout=120, journal_path=output / "requests.jsonl", max_request_cost_usd=request_cap)
        before = budget.cost_usd
        try:
            try:
                row = await protocol_case(lookup[entry["id"]], endpoint, root, entry["mode"])
                complete = budget.usage_known and not endpoint.stop_reason
            except Exception as exc:
                row, complete = {**entry, "passed": False, "evaluator_error": type(exc).__name__}, False
            row.update(evaluation_complete=complete, calls=len(endpoint.receipts), receipts=endpoint.receipts,
                       conservative_cost_usd=budget.cost_usd - before if budget.usage_known else None)
            rows.append(row)
            (output / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            if not complete:
                stop = endpoint.stop_reason or "unknown usage or evaluator failure"
                break
        finally:
            await endpoint.client.close()
    paired = [case["id"] for case in cases if {row["mode"] for row in rows if row["id"] == case["id"] and row["evaluation_complete"]} == {"prompt_json", "native"}]
    summary = {}
    from gateway.model_usage import cached_tokens
    for mode in ("prompt_json", "native"):
        selected = [row for row in rows if row["mode"] == mode and row["id"] in paired]
        receipts = [receipt for row in selected for receipt in row["receipts"]]
        caches = [cached_tokens(receipt["usage"]) for receipt in receipts]
        summary[mode] = {"paired_cases": len(selected), "passed": sum(row["passed"] for row in selected),
            "calls": len(receipts), "protocol_errors": sum(row["protocol_errors"] for row in selected),
            "truncations": sum(row["truncations"] for row in selected), "effective_actions": sum(row["effective_actions"] for row in selected),
            "unsafe_dispatches": sum(row["unsafe_dispatches"] for row in selected),
            "prompt_tokens": sum(receipt["usage"]["prompt_tokens"] for receipt in receipts),
            "completion_tokens": sum(receipt["usage"]["completion_tokens"] for receipt in receipts),
            "cache_hit_tokens": sum(caches) if caches and all(value is not None for value in caches) else None,
            "reasoning_tokens": sum((receipt["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens") or 0 for receipt in receipts)
                if receipts and all((receipt["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens") is not None for receipt in receipts) else None,
            "conservative_cost_usd": sum(row["conservative_cost_usd"] for row in selected)}
    exposure = journal_exposure(output / "requests.jsonl")
    report = {**plan, "mode": "protocol_pilot", "endpoint": endpoint.identity, "rates": rates, "paired_cases": paired,
              "cases": rows, "summary": summary, "usage_known": budget.usage_known, "calls": sum(row["calls"] for row in rows), "total_calls_including_prior": budget.calls,
              "current_known_cost_usd": budget.cost_usd - (prior["known_conservative_cost_usd"] if prior else 0),
              "known_conservative_cost_usd": budget.cost_usd, **exposure, "exposure_upper_usd": budget.cost_usd + exposure["unknown_reserve_usd"],
              "stop_reason": stop,
              "limits": "One trial per case/mode, not statistical proof. Native uses canonical action functions, not per-registry-tool functions or provider strict mode. Registry/schema context is common; only wire format differs. Native reasoning/tool-result replay is preserved and billed. Execution uses real ActionService/CapabilityService with local Workspace tools and an inert approval fixture. No product protocol switch, live MCP/network tool, UI or budget-policy comparison is claimed."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.eval")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--max-request-cost-usd", type=float, required=True)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--prior-run", type=Path)
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_worker:
        if ROOT.name != "code" or not ROOT.parent.name.startswith("isolation-"):
            parser.error("worker requires an isolated source snapshot")
        result = asyncio.run(run(args.output, args.env_file, args.max_cost_usd, args.max_request_cost_usd, args.seed, args.prior_run))
        print(json.dumps({key: result[key] for key in ("calls", "known_conservative_cost_usd", "unknown_reserve_usd", "stop_reason", "summary")}))
    else:
        from tests.support.snapshot import copy_production_code
        from tests.support.production import environment
        from tests.support.process import run_bounded
        output = args.output.resolve()
        if not output.is_relative_to(ROOT / ".tmp/evaluations"):
            parser.error("output must stay inside .tmp/evaluations")
        if args.prior_run and not args.prior_run.resolve().is_relative_to(ROOT / ".tmp/evaluations"):
            parser.error("prior report must stay inside .tmp/evaluations")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="isolation-", dir=output.parent) as temporary:
            code = Path(temporary) / "code"
            code.mkdir()
            copy_production_code(code)
            (code / "scripts").mkdir(exist_ok=True)
            for name in ("evaluate_protocol.py", "evaluate_task_progress.py"):
                shutil.copyfile(ROOT / "scripts" / name, code / "scripts" / name)
            (code / "tests/evaluation").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "tests/evaluation/protocol-live.json", code / "tests/evaluation/protocol-live.json")
            env = environment(code)
            env.update(MEMORY__ENABLED="false", MEMORY__NEO4J__ENABLED="false", SELF_EVOLVE__ENABLED="false")
            command = [sys.executable, str(code / "scripts/evaluate_protocol.py"), "--live", "--isolated-worker", "--env-file", str(args.env_file.resolve()),
                       "--output", str(output), "--max-cost-usd", str(args.max_cost_usd), "--max-request-cost-usd", str(args.max_request_cost_usd), "--seed", str(args.seed)]
            if args.prior_run:
                command += ["--prior-run", str(args.prior_run.resolve())]
            raise SystemExit(run_bounded(command, cwd=code, env=env, timeout=1860))
