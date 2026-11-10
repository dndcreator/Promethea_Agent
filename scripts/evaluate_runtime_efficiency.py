"""Paired offline Runtime replay, not a model-quality or provider-billing benchmark."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support.evaluation import digest

ASSET = ROOT / "tests/evaluation/runtime-efficiency.json"


class ReplayModel:
    def __init__(self, case):
        self.case, self.calls = case, []

    async def call_llm(self, messages, user_config=None, **_kwargs):
        maximum = (user_config or {}).get("api", {}).get("max_tokens", 2000)
        self.calls.append({"input_chars": len(json.dumps(messages, ensure_ascii=False)), "max_tokens": maximum})
        facts = []
        for message in messages:
            if isinstance(message.get("content"), list):
                for block in message["content"]:
                    if block.get("type") == "text":
                        try:
                            facts.append(json.loads(block["text"]))
                        except (ValueError, TypeError):
                            pass
        written = next((fact for fact in facts if isinstance(fact, dict) and fact.get("subject") == "workspace.write_file" and fact.get("status") == "completed"), None)
        stopped = any(isinstance(fact, dict) and (fact.get("error") or {}).get("code") in {"ACTION_BUDGET_EXHAUSTED", "MODEL_RECOVERY_EXHAUSTED"} for fact in facts)
        if written or stopped or self.case["mode"] == "answer":
            action = {"action": "answer", "content": "Observed artifact retained." if written else "No artifact delivery is verified."}
            return {"status": "success", "content": json.dumps(action)}
        if self.case["mode"] == "invalid":
            return {"status": "success", "content": "<calls>unrecognized protocol</calls>"}
        if maximum < self.case["required_output"]:
            return {"status": "error", "code": "MODEL_OUTPUT_LIMIT", "finish_reason": "length", "max_tokens": maximum, "content": '{"action":"tool_call","args":'}
        return {"status": "success", "content": json.dumps({"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "result.txt", "content": "ORCHID-29"}})}


async def measure(case, root):
    from config import PrometheaConfig
    from gateway.action.observation import RuntimeObservation
    from gateway.runtime_io import ContextCompiler
    if case["kind"] == "projection":
        observations = [RuntimeObservation(action_loop_id="replay", model_step_id=f"s{i}", tool_call_id=f"c{i}",
            tool_name="fixture.read", observation_id=f"obs{i}", ok=not case.get("error"),
            structured_result={"body": "x" * case["body_chars"], "revision": i},
            error={"code": "DEPENDENCY_MISSING", "category": "capability", "retryable": False, "message": "missing dependency", "detail": "x" * case["body_chars"]} if case.get("error") else None)
            for i in range(case["count"])]
        messages = [{"role": "system", "content": "Stable safety and action contract."}, *[{"role": "user", "content": row.model_content()} for row in observations]]
        original = deepcopy(messages)
        policy = PrometheaConfig(_env_file=None).action
        projected = ContextCompiler.project_observations(messages, [row.as_dict() for row in observations], per_result_chars=policy.observation_chars, total_chars=policy.observation_history_chars)
        return {"id": case["id"], "kind": case["kind"], "calls": 0,
                "input_chars": len(json.dumps(projected, ensure_ascii=False)), "raw_chars": len(json.dumps(messages, ensure_ascii=False)),
                "checks_passed": original == messages, "task_delivered": None}
    from tests.support.runtime import runtime_at
    from gateway.protocol import RequestType
    model = ReplayModel(case)
    host = runtime_at(root, model)
    response = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Create and retain result.txt containing ORCHID-29", "session_id": "replay"}, user_id="alice")
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="replay")
    file = Path(handle.root_path) / "result.txt"
    delivered = file.exists() and file.read_text(encoding="utf-8") == "ORCHID-29"
    expected = case["mode"] != "output" or case["required_output"] > 8192 or delivered
    return {"id": case["id"], "kind": case["kind"], "calls": len(model.calls), "input_chars": sum(row["input_chars"] for row in model.calls),
            "output_limits": [row["max_tokens"] for row in model.calls], "checks_passed": response.ok and expected,
            "task_delivered": delivered if case["mode"] == "output" else None}


async def run(output, baseline=None):
    corpus = json.loads(ASSET.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(dir=output, prefix="isolated-") as temporary:
        for case in corpus["cases"]:
            root = Path(temporary) / case["id"]
            root.mkdir()
            rows.append(await measure(case, root))
    report = {"version": 1, "corpus_hash": digest(corpus), "mode": "offline_scripted_boundary", "model_quality_measured": False,
              "model_api_calls": 0, "provider_cost_usd": None, "provider_tokens": None, "cache_hit_tokens": None,
              "cases": rows, "calls": sum(row["calls"] for row in rows), "input_chars": sum(row["input_chars"] for row in rows),
              "checks_passed": sum(row["checks_passed"] for row in rows)}
    if baseline:
        before = json.loads(baseline.read_text(encoding="utf-8"))
        if before["corpus_hash"] != report["corpus_hash"]:
            raise ValueError("cannot compare different corpora")
        report["comparison"] = {key: {"before": before[key], "after": report[key], "delta": report[key] - before[key]} for key in ("calls", "input_chars", "checks_passed")}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("calls", "input_chars", "checks_passed", "model_api_calls")}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.eval")
    parser.add_argument("--repeat", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument("--summarize", type=Path)
    args = parser.parse_args()
    if args.summarize:
        from tests.support.runtime_efficiency import paired_summary
        report = json.loads(args.summarize.read_text(encoding="utf-8"))
        args.output.mkdir(parents=True, exist_ok=True)
        summary = paired_summary(report)
        (args.output / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
    elif args.live:
        from tests.support.runtime_efficiency import run_live
        corpus = json.loads((ROOT / "tests/evaluation/runtime-efficiency-live.json").read_text(encoding="utf-8"))
        if args.cases:
            corpus["cases"] = [case for case in corpus["cases"] if case["id"] in args.cases]
            if len(corpus["cases"]) != len(set(args.cases)):
                raise ValueError("unknown or duplicate case selection")
        result = asyncio.run(run_live(args.output.resolve(), args.env_file, corpus, args.repeat, args.previous_report))
        print(json.dumps({key: result[key] for key in ("model_api_calls", "conservative_cost_usd", "usage_known", "stop_reason", "fully_paired_cases")}, ensure_ascii=False))
    else:
        asyncio.run(run(args.output.resolve(), args.baseline))
