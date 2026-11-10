"""Opt-in per-call output-contract pilot; no production budget changes."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(output, env_file, maximum):
    from scripts.evaluate_task_progress import run_live
    from tests.support.call_budget import call_budget_case
    from tests.support.evaluation import Budget
    ledger = Budget(max_calls=180, max_tokens=1500000, seconds=3600, max_cost_usd=maximum)
    report = await run_live(output, env_file, maximum, 2, ROOT / "tests/evaluation/call-budget-live.json", 20261102, 120,
                            max_request_cost=0.03, shared_budget=ledger, case_runner=call_budget_case)
    report["mode"] = "per_call_output_contract_pilot"
    comparable = {tuple(group) for group in report["summary"]["comparable_groups"]}
    for policy_id, summary in report["summary"]["policies"].items():
        changes = [change for row in report["cases"] if row["condition"] == policy_id and (row["trial"], row["id"]) in comparable
                   for change in row.get("budget_adjustments", [])]
        summary["truncation_recovery_increases"] = sum(change["after"] > change["before"] and change["reason"] == "real_truncation_recovery" for change in changes)
        summary["output_scope_increases"] = sum(change["after"] > change["before"] and change["reason"] == "runtime_output_scope_changed" for change in changes)
        summary["output_scope_decreases"] = sum(change["after"] < change["before"] and change["reason"] == "runtime_output_scope_changed" for change in changes)
    report["limits"] = (
        "All arms share the same enforced phase contracts, Prompt JSON, tool/runtime permissions, default provider thinking and acceptance checks. "
        "Only the candidate chooses per-call 4096 for an enforced <=1024-character action contract, otherwise 8192. "
        "Final-answer-only is not assumed short. Truncation uses existing bounded recovery; a changed candidate contract resets only its allowance, not recovery counters. "
        "The old structural prior is unchanged and uses only the common public delivery contract. Private gold/checks never enter model inputs. "
        "This tests declared phase contracts, not a predictor of arbitrary next actions or a shipped product policy. Three tasks/two repeats are a pilot, not statistical proof. "
        "Missing runs after admission/unknown-usage stops are unscored, not task failures. Known prices are conservative configured estimates, not an invoice."
    )
    archive = output.parent / f"{output.name}-source.zip"
    if archive.is_file():
        report["source_archive"] = {"path": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.eval")
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_worker:
        if ROOT.name != "code" or not ROOT.parent.name.startswith("isolation-"):
            parser.error("worker requires an isolated snapshot")
        report = asyncio.run(run(args.output, args.env_file, args.max_cost_usd))
        print(json.dumps({key: report[key] for key in ("model_api_calls", "conservative_cost_usd", "stop_reason", "summary")}))
    else:
        from tests.support.snapshot import copy_production_code
        from tests.support.production import environment
        from tests.support.process import run_bounded
        output = args.output.resolve()
        if not output.is_relative_to(ROOT / ".tmp/evaluations"):
            parser.error("evidence must remain inside .tmp/evaluations")
        if output.exists() and any(output.iterdir()):
            parser.error("preserve previous evidence; choose a fresh output")
        archive = output.parent / f"{output.name}-source.zip"
        if archive.exists():
            parser.error("preserve previous source archive; choose a fresh output")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="isolation-", dir=output.parent) as temporary:
            code = Path(temporary) / "code"
            code.mkdir()
            copy_production_code(code)
            (code / "scripts").mkdir(exist_ok=True)
            for name in ("evaluate_call_budget.py", "evaluate_task_progress.py"):
                shutil.copyfile(ROOT / "scripts" / name, code / "scripts" / name)
            (code / "tests/evaluation").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "tests/evaluation/call-budget-live.json", code / "tests/evaluation/call-budget-live.json")
            if (code / ".env").exists() or (code / "config/users").exists():
                raise RuntimeError("source snapshot contains deployment state")
            shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=code)
            env = environment(code)
            env["CANVAS_TEST_BROWSER_CHANNEL"] = "msedge"
            sys.exit(run_bounded([sys.executable, str(code / "scripts/evaluate_call_budget.py"), "--live", "--isolated-worker", "--env-file", str(args.env_file.resolve()),
                                  "--output", str(output), "--max-cost-usd", str(args.max_cost_usd)], cwd=code, env=env, timeout=3750))
