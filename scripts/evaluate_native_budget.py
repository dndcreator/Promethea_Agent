"""Product Native smoke + frozen Prompt JSON budget test, one admission ledger."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support.evaluation import Budget, digest, journal_exposure


async def run(output, env_file, maximum):
    from config import config
    from tests.support.runtime_efficiency import eval_settings
    from tests.support.protocol_eval import RuntimeNativeEndpoint, protocol_case
    from scripts.evaluate_task_progress import run_live, source_fingerprint, experiment_schedule

    if not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("explicit positive total authorization required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("preserve prior evidence; use a fresh directory")
    values, _, rates = eval_settings(env_file)
    corpus_path = ROOT / "tests/evaluation/budget-independent-live.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    protocol = json.loads((ROOT / "tests/evaluation/protocol-live.json").read_text(encoding="utf-8"))
    native_cases = [case for case in protocol["cases"] if case["id"] in {"write", "inspect", "approval"}]
    output.mkdir(parents=True)
    plan = {"version": 1, "source_hash": source_fingerprint(), "native_corpus_hash": digest(native_cases),
            "budget_corpus_hash": digest(corpus), "total_authorization_usd": maximum, "rates": rates,
            "request_reserve_cap_usd": 0.03, "timeout_seconds": 120, "seed": 20261101,
            "native_cases": native_cases, "budget_schedule": experiment_schedule(corpus, 2, 20261101)}
    archive = output.parent / f"{output.name}-source.zip"
    if archive.is_file():
        plan["source_archive"] = {"path": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    budget = Budget(max_calls=240, max_tokens=2400000, seconds=5400, max_cost_usd=maximum)
    endpoint = RuntimeNativeEndpoint(values, budget, rates, request_timeout=120, journal_path=output / "native/requests.jsonl", max_request_cost_usd=0.03)
    original = config.api.tool_protocol
    rows, stopped = [], None
    try:
        config.api.tool_protocol = "native"
        for case in native_cases:
            before, cost = len(endpoint.receipts), budget.cost_usd
            root = output / "native" / case["id"]
            root.mkdir(parents=True)
            try:
                row = await protocol_case(case, endpoint, root, "native")
                row["evaluation_complete"] = budget.usage_known and not endpoint.stop_reason
            except Exception as exc:
                row = {"id": case["id"], "evaluation_complete": False, "evaluator_error": type(exc).__name__}
            row.update(receipts=deepcopy(endpoint.receipts[before:]), conservative_cost_usd=budget.cost_usd - cost)
            rows.append(row)
            (output / "native/progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            if not row["evaluation_complete"] or not row.get("passed"):
                stopped = endpoint.stop_reason or "native acceptance incomplete or failed"
                break
    finally:
        config.api.tool_protocol = original
        await endpoint.client.close()
    native_exposure = journal_exposure(output / "native/requests.jsonl")
    native_report = {"cases": rows, "calls": budget.calls, "conservative_cost_usd": budget.cost_usd, **native_exposure, "stop_reason": stopped}
    (output / "native/report.json").write_text(json.dumps(native_report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = None
    if not stopped and budget.usage_known and not native_exposure["unresolved_requests"]:
        config.api.tool_protocol = "prompt_json"
        try:
            result = await run_live(output / "budget", env_file, maximum, 2, corpus_path, 20261101, 120,
                                    max_request_cost=0.03, shared_budget=budget)
        finally:
            config.api.tool_protocol = original
    report = {**plan, "native": native_report, "budget_report": "budget/report.json" if result else None,
              "total_calls": budget.calls, "known_cost_usd": budget.cost_usd, "usage_known": budget.usage_known,
              "unknown_reserve_usd": native_exposure["unknown_reserve_usd"] + ((result or {}).get("request_journal") or {}).get("unknown_reserve_usd", 0),
              "stop_reason": stopped or (result or {}).get("stop_reason"),
              "limits": "Native live smoke uses the product wire codec and Action/Capability execution, with metered single-provider test transport; product streaming and restart are tested offline. No other provider credentials are used. Budget arms use frozen Prompt JSON. Missing runs are not task failures. Costs are conservative configured estimates, not an invoice."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.eval")
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_worker:
        if ROOT.name != "code" or not ROOT.parent.name.startswith("isolation-"):
            parser.error("worker requires an isolated snapshot")
        report = asyncio.run(run(args.output, args.env_file, args.max_cost_usd))
        print(json.dumps({key: report[key] for key in ("total_calls", "known_cost_usd", "usage_known", "unknown_reserve_usd", "stop_reason")}))
    else:
        from tests.support.snapshot import copy_production_code
        from tests.support.production import environment
        from tests.support.process import run_bounded
        output = args.output.resolve()
        if not output.is_relative_to(ROOT / ".tmp/evaluations"):
            parser.error("evidence must remain inside .tmp/evaluations")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="isolation-", dir=output.parent) as temporary:
            code = Path(temporary) / "code"
            code.mkdir()
            copy_production_code(code)
            (code / "scripts").mkdir(exist_ok=True)
            for name in ("evaluate_native_budget.py", "evaluate_task_progress.py"):
                shutil.copyfile(ROOT / "scripts" / name, code / "scripts" / name)
            (code / "tests/evaluation").mkdir(parents=True, exist_ok=True)
            for name in ("protocol-live.json", "budget-independent-live.json"):
                shutil.copyfile(ROOT / "tests/evaluation" / name, code / "tests/evaluation" / name)
            if (code / ".env").exists() or (code / "config/users").exists():
                raise RuntimeError("source snapshot unexpectedly contains deployment configuration")
            archive = output.parent / f"{output.name}-source.zip"
            if archive.exists():
                raise FileExistsError("preserve previous source evidence; use a fresh output name")
            shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=code)
            env = environment(code)
            env["CANVAS_TEST_BROWSER_CHANNEL"] = "msedge"
            sys.exit(run_bounded([sys.executable, str(code / "scripts/evaluate_native_budget.py"), "--live", "--isolated-worker", "--env-file", str(args.env_file.resolve()),
                                  "--output", str(output), "--max-cost-usd", str(args.max_cost_usd)], cwd=code, env=env, timeout=5700))
