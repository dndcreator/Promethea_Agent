"""Opt-in, shared-budget production A/B trial. No scripted Agent business actions."""
from __future__ import annotations

import argparse
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.production import prepare_deployment, production_server
from tests.support.metered_proxy import MeteredProxy
from tests.support.runtime_efficiency import calculator_check, eval_settings

TREATMENT_FILES = (
    "gateway/tools/projection.py", "gateway/tool_prompt_blocks.py", "gateway/prompt_assembler.py",
    "gateway/conversation_service.py", "gateway/action/service.py", "gateway/capability_service.py",
)
STABILITY_FILES = (
    "gateway/action/model_action.py", "gateway/action/service.py", "gateway/model_protocol.py",
    "gateway/runtime_io.py", "gateway/tool_prompt_blocks.py",
)
CALCULATOR_GOAL = (
    "在隔离工作区交付一个可独立打开的 calculator.html 加法计算器，不要只给解释。"
    "界面包含两个数字输入框（id=a、id=b）、计算按钮（id=calculate）和结果（id=result）；"
    "支持负数和小数，无需外部资源。请使用你实际可用的能力完成，缺少信息时自行查询。"
    "不要更改主机文件、安装系统软件或绕过审批。文件必须真实存在并可交互。"
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def function_ast(path, owner, name):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return ast.dump(next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), include_attributes=False)


def prepare_variants(output, frozen, *, profile="tool-context"):
    treatment = STABILITY_FILES if profile == "request-stability" else TREATMENT_FILES
    roots = {condition: output / condition for condition in ("baseline", "candidate")}
    for root in roots.values():
        prepare_deployment(root)
    for relative in treatment:
        source = frozen / relative
        if not source.is_file():
            raise ValueError("missing frozen baseline source: " + relative)
        shutil.copyfile(source, roots["baseline"] / relative)
    for owner, relative, names in (
        ("CapabilityService", "gateway/capability_service.py", ("call_tool", "_authorize_tool_call")),
        ("ActionService", "gateway/action/service.py", () if profile == "request-stability" else ("_execute_call", "_execute_batch", "_control_progress")),
    ):
        for name in names:
            if function_ast(roots["baseline"] / relative, owner, name) != function_ast(roots["candidate"] / relative, owner, name):
                raise ValueError("baseline differs in protected execution/policy code: " + name)
    hashes = {condition: {relative: sha(root / relative) for relative in treatment} for condition, root in roots.items()}
    for path in roots["candidate"].rglob("*"):
        if path.is_file() and path.suffix in {".py", ".js", ".yaml", ".toml", ".json"}:
            relative = path.relative_to(roots["candidate"]).as_posix()
            if relative not in treatment and sha(path) != sha(roots["baseline"] / relative):
                raise ValueError("non-treatment source differs: " + relative)
    return roots, hashes


def request_stability(events):
    """Inspect retained wire facts, not provider reasoning or claimed task success."""
    batches, rewrites, definitions = [], [], []
    previous = {}
    for event in events:
        if event.get("event_type") != "model.call.recorded":
            continue
        payload = event["payload"]
        packet = payload.get("provider_message") or {}
        operations = [call.get("function", {}).get("name") for call in packet.get("tool_calls") or []]
        batches.append({"model_step_id": payload.get("model_step_id"), "purpose": payload.get("purpose"),
                        "operations": operations,
                        "mixed_query_and_tool": bool(set(operations) & {"capability_inspect", "capability_request"}
                                                     and set(operations) & {"tool_call", "tool_calls"})})
        wire = payload.get("wire_request")
        if not wire:
            continue
        definitions.append(hashlib.sha256(json.dumps(wire.get("tools"), sort_keys=True).encode()).hexdigest())
        current = {}
        for message in wire.get("messages") or []:
            if message.get("role") != "tool":
                continue
            try:
                value = json.loads(message.get("content") or "")
            except (ValueError, TypeError):
                continue
            for fact in value.get("observations") or []:
                identifier = fact.get("observation_id")
                if identifier:
                    current[identifier] = json.dumps(fact, sort_keys=True, ensure_ascii=False)
                    if identifier in previous and previous[identifier] != current[identifier]:
                        rewrites.append({"model_step_id": payload.get("model_step_id"), "observation_id": identifier})
        previous = current
    return {"native_batches": batches, "prior_observation_rewrites": rewrites,
            "function_definition_changes": sum(first != second for first, second in zip(definitions, definitions[1:]))}


def summarize_pair(rows, case):
    pair = {row["condition"]: row for row in rows if row["case"] == case}
    if set(pair) != {"baseline", "candidate"}:
        return {"paired": False, "reason": "missing arm"}
    comparable = all(row["calls"] > 0 and not row["admission_denied"] and row["usage_known"] and not row.get("driver_error") for row in pair.values())
    costs = {key: value["cost_usd"] for key, value in pair.items()}
    conclusion = "incomplete or censored pair; no cost or quality comparison"
    if comparable:
        conclusion = ("unverified external account/repository" if case == "github" else
                      "single paired functional case; no statistical significance claim")
    return {"paired": comparable, "bounded_attempt_cost_usd": costs,
            "cost_change_percent": (costs["candidate"] / costs["baseline"] - 1) * 100 if comparable and costs["baseline"] else None,
            "delivery_verified": {key: value["delivery_verified"] for key, value in pair.items()},
            "goal_quality_conclusion": conclusion}


def unapproved_effects(executions, approvals):
    from collections import Counter
    from gateway.tools.registry import ToolRegistry
    from gateway.tools.spec import ToolSpec

    def key(name, args):
        return name, json.dumps(args or {}, sort_keys=True, ensure_ascii=False)

    approved = Counter(key(row["tool_name"], row["args"]) for row in approvals if row["decision"] == "approve")
    violations = []
    for row in executions:
        if not row.get("tool_spec"):
            continue
        spec = ToolSpec.model_validate(row["tool_spec"])
        registry = ToolRegistry()
        registry.register_spec(spec)
        args = row.get("args") or {}
        effect = registry.resolve_for_call(tool_name=spec.full_name, params=args).side_effect_level
        if effect not in {"external_write", "privileged_host_action"}:
            continue
        signature = key(spec.full_name, args)
        if approved[signature]:
            approved[signature] -= 1
        else:
            violations.append(spec.full_name)
    return violations


def run_case(root, output, case, condition, goal, proxy, endpoint, *, max_steps=5, approval_handler=None):
    import requests
    label = case + "/" + condition
    token = "fixture-" + hashlib.sha256(label.encode()).hexdigest()
    with proxy.lock:
        proxy.request_labels[token] = label
    row = {"case": case, "condition": condition, "label": label,
           "delivery_verified": False if case in {"calculator", "github"} else None,
           "approval_automation": False, "driver_business_actions": [], "terminal_events": [], "user_approvals": []}
    config_path = root / "config/default.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg.update(memory={"enabled": False, "store_backend": "sqlite_graph", "neo4j": {"enabled": False}}, ambient={"enabled": False}, self_evolve={"enabled": True},
               moirai_learning={"enabled": False}, action={"max_steps": max_steps, "gaps": {"enabled": True}},
               system={"browser_headless": False, "browser_channel": "msedge", "browser_auto_install": False})
    cfg["api"].update(base_url=endpoint, api_key=token, model=proxy.model, tool_protocol="native",
                      timeout=120, max_tokens=8192, output_token_limit=8192, retry_count=0)
    save(config_path, cfg)
    gateway_path = root / "gateway_config.json"
    gateway = json.loads(gateway_path.read_text())
    gateway["computer"]["enabled_controllers"] = ["browser", "filesystem"]
    save(gateway_path, gateway)
    session = "comparison-" + case
    started = time.monotonic()
    try:
        with production_server(root) as (base, log):
            with requests.Session() as client:
                registered = client.post(base + "/api/auth/register", json={"username": "context-evaluation", "password": "disposable-runtime-only"}, timeout=20)
                # Each case has a fresh deployment, so an existing identity is a fixture error.
                registered.raise_for_status()
                login = client.post(base + "/api/auth/login", json={"username": "context-evaluation", "password": "disposable-runtime-only"}, timeout=20)
                login.raise_for_status()
                client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
                client.post(base + "/api/config/update", json={"validate": False, "config": {"tools": {"allow": []}}}, timeout=20).raise_for_status()
                with client.post(base + "/api/chat", json={"session_id": session, "message": goal, "stream": True}, stream=True, timeout=(10, 900)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line.startswith(b"data: "):
                            event = json.loads(line[6:])
                            with (output / "sse.jsonl").open("a", encoding="utf-8") as stream:
                                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                            if event.get("type") in {"done", "error", "needs_input", "needs_confirmation"}:
                                row["terminal_events"].append(event)
                while approval_handler and row["terminal_events"] and proxy.budget.usage_known:
                    pending = row["terminal_events"][-1]
                    if pending.get("status") != "needs_confirmation" or not pending.get("tool_call_id"):
                        break
                    decision = approval_handler(pending)
                    if decision not in {"approve", "reject"}:
                        break
                    row["user_approvals"].append({"tool_call_id": pending["tool_call_id"], "decision": decision,
                                                  "tool_name": pending.get("tool_name"), "args": pending.get("args")})
                    resumed = client.post(base + "/api/chat/confirm", json={"session_id": session,
                                          "tool_call_id": pending["tool_call_id"], "action": decision}, timeout=(10, 900))
                    resumed.raise_for_status()
                    row["terminal_events"].append(resumed.json())
                detail = client.get(base + "/api/sessions/" + session, timeout=20)
                detail.raise_for_status()
                save(output / "session.json", detail.json())
            shutil.copyfile(log, output / "launcher.log")
    except Exception as exc:
        row["driver_error"] = type(exc).__name__ + ": " + str(exc)
    log_path = root / "gateway/runtime_events.jsonl"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []
    if log_path.exists():
        shutil.copyfile(log_path, output / "runtime-events.jsonl")
    row.update(request_stability(events))
    observations = [event["payload"] for event in events if event["event_type"] == "action.observation.committed"]
    row["observations"] = [{key: obs.get(key) for key in ("observation_id", "tool_name", "ok", "error")} for obs in observations]
    executions = [event["payload"] for event in events if event["event_type"] == "tool.execution.started"]
    row["tool_executions"] = len(executions)
    row["successful_observations"] = sum(obs.get("ok") is True for obs in observations)
    row["unapproved_sensitive_executions"] = unapproved_effects(executions, row["user_approvals"])
    if row["unapproved_sensitive_executions"]:
        raise AssertionError("a sensitive operation executed without approval")
    if case == "calculator":
        files = list((root / "workspace").glob("*/" + session + "/calculator.html"))
        row["artifact_count"] = len(files)
        if len(files) == 1:
            artifact = files[0]
            row["artifact_sha256"] = sha(artifact)
            shutil.copyfile(artifact, output / "calculator.html")
            try:
                row["delivery_verified"] = asyncio.run(calculator_check(artifact.read_text(encoding="utf-8")))
            except Exception as exc:
                row["verification_error"] = type(exc).__name__ + ": " + str(exc)
    row["seconds"] = round(time.monotonic() - started, 3)
    row["receipts"] = [receipt for receipt in proxy.receipts if receipt.get("label") == label]
    row["calls"] = len(row["receipts"])
    row["usage_known"] = all(receipt.get("usage") for receipt in row["receipts"])
    row["input_tokens"] = sum(receipt["usage"]["prompt_tokens"] for receipt in row["receipts"] if receipt.get("usage"))
    row["output_tokens"] = sum(receipt["usage"]["completion_tokens"] for receipt in row["receipts"] if receipt.get("usage"))
    from gateway.model_usage import cached_tokens
    usages = [receipt["usage"] for receipt in row["receipts"] if receipt.get("usage")]
    cache = [cached_tokens(usage) for usage in usages]
    row["cache_hit_tokens"] = sum(cache) if all(value is not None for value in cache) else None
    reasoning = [(usage.get("completion_tokens_details") or {}).get("reasoning_tokens") for usage in usages]
    row["reasoning_tokens"] = sum(reasoning) if all(value is not None for value in reasoning) else None
    row["cost_usd"] = (row["input_tokens"] * proxy.rates[0] + row["output_tokens"] * proxy.rates[1]) / 1_000_000 if row["usage_known"] else None
    journal = [json.loads(line) for line in (proxy.output / "requests.jsonl").read_text().splitlines()] if (proxy.output / "requests.jsonl").exists() else []
    row["admission_denied"] = [record for record in journal if record.get("label") == label and record["state"] == "not_sent"]
    save(output / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized-usd", type=float, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--profile", choices=("tool-context", "request-stability"), default="tool-context")
    parser.add_argument("--goal-plan", type=Path)
    parser.add_argument("--candidate-only", action="store_true", help="Retest current source only; do not pay to repeat a known baseline defect")
    args = parser.parse_args()
    if not args.live or not math.isfinite(args.authorized_usd) or args.authorized_usd <= 0:
        parser.error("requires explicit live opt-in and a positive authorized ceiling")
    output, frozen = args.output.resolve(), args.baseline.resolve()
    if not output.is_relative_to(ROOT / ".tmp") or not frozen.is_relative_to(ROOT / ".tmp") or output.exists():
        parser.error("use a new ignored output directory and retained local baseline")
    output.mkdir(parents=True)
    values, _, rates = eval_settings(ROOT / ".env.eval")
    proxy = MeteredProxy(values, rates, output, ceiling=args.authorized_usd)
    proxy.budget.max_calls, proxy.budget.max_tokens, proxy.budget.seconds = 24, 2_000_000, 1200
    source_plan = json.loads((args.goal_plan or frozen.parent / "plan.json").read_text(encoding="utf-8"))
    goal = source_plan.get("goal") or source_plan["goals"]["github"]
    order = ([["calculator", "candidate"], ["calculator", "baseline"], ["github", "baseline"], ["github", "candidate"]]
             if args.profile == "request-stability" else
             [["github", "baseline"], ["github", "candidate"], ["calculator", "candidate"], ["calculator", "baseline"]])
    if args.candidate_only:
        order = [[case, condition] for case, condition in order if condition == "candidate"]
    plan = {"authorized_usd": args.authorized_usd, "price_ceilings": rates, "model": proxy.model,
            "source_baseline": str(frozen), "profile": args.profile, "candidate_only": args.candidate_only,
            "treatment_files": [] if args.candidate_only else STABILITY_FILES if args.profile == "request-stability" else TREATMENT_FILES,
            "order": order,
            "max_action_steps": 5, "output_limit": 8192, "provider_timeout": 120,
            "goals": {"github": goal, "calculator": CALCULATOR_GOAL}, "automatic_approvals": False,
            "calculator_criterion": "Actual browser clicks: numeric result or explicit input-addition equation; operands and result must match.",
            "quality_rule": "Verify actual outcomes; external blockage is not goal success. Single pairs cannot establish statistical noninferiority.",
            "started_at": datetime.now(timezone.utc).isoformat()}
    save(output / "plan.json", plan)
    rows = []
    report = {"plan": plan, "runs": rows}
    try:
        with proxy.serve() as endpoint:
            for case, condition in plan["order"]:
                if not proxy.budget.usage_known or proxy.budget.remaining() <= 0:
                    break
                case_root = output / (case + "-pair")
                if not case_root.exists():
                    case_root.mkdir()
                    if args.candidate_only:
                        root = case_root / "candidate"
                        prepare_deployment(root)
                        hashes = {"candidate": {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*.py")}}
                    else:
                        roots, hashes = prepare_variants(case_root, frozen, profile=args.profile)
                    save(case_root / "source-hashes.json", hashes)
                root = case_root / condition
                evidence = output / (case + "-" + condition)
                evidence.mkdir()
                rows.append(run_case(root, evidence, case, condition, plan["goals"][case], proxy, endpoint))
                report["pairs"] = {name: summarize_pair(rows, name) for name in ("github", "calculator")}
                save(output / "report.partial.json", report)
    finally:
        report.update(cost_usd=proxy.budget.cost_usd, usage_known=proxy.budget.usage_known,
                      calls=proxy.budget.calls, receipts=proxy.receipts, stop_reason=proxy.stop_reason,
                      pairs={name: summarize_pair(rows, name) for name in ("github", "calculator")})
        save(output / "report.json", report)
    print(json.dumps({key: report[key] for key in ("cost_usd", "usage_known", "calls", "pairs")}, ensure_ascii=False, indent=2))
    return 0 if proxy.budget.usage_known else 2


if __name__ == "__main__":
    raise SystemExit(main())
