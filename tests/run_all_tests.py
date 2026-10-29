"""Bounded test runner. Model quality uses scripts/run_evaluations.py."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.reporting import compare_runs, read_junit
from tests.support.process import run_bounded


def main(argv=None):
    suites = json.loads((ROOT / "tests/evaluation/suites.json").read_text(encoding="utf-8"))
    layers = {"unit": "unit", "integration": "integration", "system": "system and not browser", "browser": "browser", "live": "live", "stress": "stress"}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=[*layers, "full", *[key for key in suites if key not in {"version", "unit"}]], default=None)
    parser.add_argument("--file")
    parser.add_argument("--pattern", default="")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--timeout", type=int, default=600, help="total wall-clock budget, including repeats")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path, help="previous JUnit XML")
    args = parser.parse_args(argv)
    args.suite = args.suite or ("full" if args.file else "unit")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if args.suite == "live" and not args.live:
        parser.error("live suite requires --live and explicit deployment settings")
    if args.live and args.suite != "live":
        parser.error("--live is restricted to the read-only live suite; host interaction tests require separate explicit opt-in")
    env = os.environ.copy()
    env.pop("PROMETHEA_LIVE_TEST", None)
    env.pop("RUN_STRESS_TESTS", None)
    if args.live:
        env["PROMETHEA_LIVE_TEST"] = "1"
    if args.suite == "stress":
        env["RUN_STRESS_TESTS"] = "1"
    if args.suite == "browser" and not all(env.get(key) for key in ("CANVAS_TEST_BROWSER_CHANNEL", "PROMETHEA_UI_TEST_URL")):
        parser.error("browser suite requires CANVAS_TEST_BROWSER_CHANNEL and PROMETHEA_UI_TEST_URL")
    output = args.output or ROOT / ".tmp/evaluations" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env["PROMETHEA_TEST_TMP_ROOT"] = str(output / "pytest-runtime")
    if args.file:
        target = (ROOT / "tests" / args.file).resolve()
        if not target.is_relative_to(ROOT / "tests") or not target.is_file():
            parser.error("--file must be an existing file inside tests/")
        targets = [str(target)]
    else:
        targets = suites.get(args.suite, ["tests"]) if args.suite not in layers else ["tests"]
    cmd = [sys.executable, "-m", "pytest", *targets, "-vv" if args.verbose else "-q"]
    if args.suite in layers:
        cmd += ["-m", layers[args.suite]]
    if args.pattern:
        cmd += ["-k", args.pattern]
    if args.coverage:
        cmd += ["--cov", "--cov-report=json:" + str(output / "coverage.json")]
        env["COVERAGE_FILE"] = str(output / ".coverage")
    report = {"version": 1, "suite": args.suite, "started_at": datetime.now(timezone.utc).isoformat(), "budget_seconds": args.timeout, "runs": [],
              "model_api_calls": None, "model_evaluation_enabled": False,
              "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())}
    started, failed = time.monotonic(), False
    for trial in range(args.repeat):
        xml = output / f"trial-{trial + 1}.xml"
        remaining = args.timeout - (time.monotonic() - started)
        if remaining <= 0:
            failed = True
            report["stop_reason"] = "wall_clock_budget"
            break
        try:
            with (output / f"trial-{trial + 1}.log").open("w", encoding="utf-8") as log:
                exit_code = run_bounded([*cmd, "--junitxml=" + str(xml)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=remaining)
            facts = read_junit(xml) if xml.exists() else {"error": "JUnit report missing"}
            failed |= exit_code != 0 or "error" in facts or bool(facts.get("totals", {}).get("failed"))
            report["runs"].append({"trial": trial + 1, "exit_code": exit_code, **facts})
            print(json.dumps(report["runs"][-1].get("totals", facts)))
        except subprocess.TimeoutExpired:
            failed = True
            report["stop_reason"] = "wall_clock_budget"
            break
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["passed"] = not failed
    if args.live:
        report["model_api_calls"] = None
    if args.compare and report["runs"] and "modules" in report["runs"][-1]:
        report["comparison"] = compare_runs(read_junit(args.compare), report["runs"][-1])
    outcomes = {}
    for run in report["runs"]:
        for row in run.get("failures", []):
            outcomes[row["case"]] = outcomes.get(row["case"], 0) + 1
    report["failure_occurrences"] = outcomes
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output / 'summary.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
