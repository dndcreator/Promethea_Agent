"""Run one user-authored local-app goal through production; grade artifacts separately."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_capability_context import run_case, save, sha
from tests.support.metered_proxy import MeteredProxy
from tests.support.production import prepare_deployment
from tests.support.runtime_efficiency import eval_settings


def app_artifacts(root):
    workspace = (root / "workspace").resolve()
    artifacts = []
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".css", ".js", ".mp4", ".webm"}:
            continue
        if any(part.startswith(".") or part == "node_modules" for part in path.relative_to(workspace).parts):
            continue
        if not path.resolve().is_relative_to(workspace):
            continue
        artifacts.append({"path": str(path.resolve()), "relative_path": path.relative_to(workspace).as_posix(),
                          "bytes": path.stat().st_size, "sha256": sha(path)})
    return artifacts


def interactive_approval(pending):
    from queue import Queue, Empty
    from threading import Thread

    identifier = pending["tool_call_id"]
    print("APPROVAL " + json.dumps({key: pending.get(key) for key in ("tool_call_id", "tool_name", "args")}, ensure_ascii=False), flush=True)
    decisions = Queue(maxsize=1)
    Thread(target=lambda: decisions.put(sys.stdin.readline().strip()), daemon=True).start()
    try:
        response = decisions.get(timeout=120)
    except Empty:
        return None
    for decision in ("approve", "reject"):
        if response == f"{decision} {identifier}":
            return decision
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "tests/evaluation/local-todo-live.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized-usd", type=float, required=True)
    parser.add_argument("--max-steps", type=int, choices=range(1, 51), default=10)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--interactive-approval", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.live or not math.isfinite(args.authorized_usd) or args.authorized_usd <= 0:
        parser.error("requires explicit live opt-in and a positive authorized ceiling")
    if not output.is_relative_to(ROOT / ".tmp") or output.exists():
        parser.error("use a fresh output directory inside ignored .tmp")
    case = json.loads(args.case.read_text(encoding="utf-8"))
    if not str(case.get("id") or "").isalnum() or not str(case.get("goal") or "").strip():
        parser.error("case requires a simple id and non-empty user goal")
    output.mkdir(parents=True)
    values, _, rates = eval_settings(ROOT / ".env.eval")
    proxy = MeteredProxy(values, rates, output, ceiling=args.authorized_usd)
    proxy.budget.max_calls, proxy.budget.max_tokens, proxy.budget.seconds = 15, 1_000_000, 1200
    deployment, evidence = output / "deployment", output / "evidence"
    prepare_deployment(deployment)
    evidence.mkdir()
    save(output / "source-hashes.json", {path.relative_to(deployment).as_posix(): sha(path) for path in deployment.rglob("*.py")})
    plan = {"case": case, "authorized_usd": args.authorized_usd, "price_ceilings": rates, "model": proxy.model,
            "max_action_steps": args.max_steps, "max_output_tokens": 8192, "provider_timeout": 120,
            "automatic_approvals": False, "memory_enabled": False, "driver_business_actions": [],
            "started_at": datetime.now(timezone.utc).isoformat()}
    save(output / "plan.json", plan)
    report = {"plan": plan, "independent_verification": "pending"}
    try:
        with proxy.serve() as endpoint:
            report["run"] = run_case(deployment, evidence, case["id"], "candidate", case["goal"], proxy, endpoint,
                                     max_steps=args.max_steps, approval_handler=interactive_approval if args.interactive_approval else None)
    finally:
        report.update(cost_usd=proxy.budget.cost_usd, usage_known=proxy.budget.usage_known,
                      calls=proxy.budget.calls, stop_reason=proxy.stop_reason, receipts=proxy.receipts,
                      app_artifacts=app_artifacts(deployment))
        save(output / "report.json", report)
    print(json.dumps({key: report[key] for key in ("cost_usd", "usage_known", "calls", "app_artifacts")}, ensure_ascii=False, indent=2))
    return 0 if proxy.budget.usage_known else 2


if __name__ == "__main__":
    raise SystemExit(main())
