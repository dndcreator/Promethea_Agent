from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.security.sandbox import SandboxPolicy
from agentkit.tools.moirai.moirai import MoiraiService
from gateway.tool_strategy import ToolStrategyEngine


def _default_catalog() -> List[Dict[str, Any]]:
    return [
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "browser_action", "description": "browser goto click type"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "perception_action", "description": "perception locate ocr screen"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "fs_action", "description": "filesystem read write list"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "process_action", "description": "run process launch app"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "content_action", "description": "fetch and parse web pdf image"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "runtime_action", "description": "runtime status plugins memory"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "schedule_action", "description": "schedule cron recurring jobs"},
        {"tool_type": "mcp", "service_name": "computer_control", "tool_name": "graph_action", "description": "graph node relation edges"},
        {"tool_type": "mcp", "service_name": "moirai", "tool_name": "flow_resume", "description": "workflow resume retry checkpoint"},
        {"tool_type": "mcp", "service_name": "self_evolve", "tool_name": "self_evolve", "description": "self evolve code patch test"},
    ]


def run_strategy_benchmark(task_file: Path) -> Dict[str, Any]:
    engine = ToolStrategyEngine()
    data = json.loads(task_file.read_text(encoding="utf-8-sig"))
    tasks = data.get("tasks", [])
    catalog = _default_catalog()
    passed = 0
    rows: List[Dict[str, Any]] = []
    for task in tasks:
        out = engine.recommend(
            step=task.get("step") or {},
            user_message=str(task.get("user_message", "")),
            observations=[],
            catalog=catalog,
            strategy_hints={},
        )
        ok = bool(out.get("use_tool")) and out.get("service_name") == task.get("expect", {}).get("service_name") and out.get("tool_name") == task.get("expect", {}).get("tool_name")
        if ok:
            passed += 1
        rows.append(
            {
                "id": task.get("id"),
                "ok": ok,
                "expected": task.get("expect"),
                "actual": {"service_name": out.get("service_name"), "tool_name": out.get("tool_name"), "confidence": out.get("confidence")},
            }
        )
    total = max(1, len(tasks))
    return {"passed": passed, "total": len(tasks), "score": round(passed / total, 3), "rows": rows}


async def run_capability_smoke(workspace_root: Path) -> Dict[str, Any]:
    moirai = MoiraiService(str(workspace_root))
    run = await moirai.create_web_task_pipeline(
        name="bench_web_pipeline",
        start_url="https://example.com",
        target_text="Download",
        auto_start=False,
    )
    has_manual_gate = any((s.get("id") == "manual_verify_gate") for s in run.get("steps", []))

    sandbox = SandboxPolicy(
        enabled=True,
        profile="strict",
        workspace_access="rw",
        command_mode="allowlist",
        allowed_commands=["python", "pytest", "rg", "powershell"],
        deny_fragments=["rm -rf"],
        network_mode="restricted",
        allowed_domains=["example.com"],
        block_private_network=True,
    )
    sandbox_ok = sandbox.check_command("python -V").allowed and not sandbox.check_command("rm -rf /").allowed

    return {
        "moirai_template_gate": has_manual_gate,
        "sandbox_guard": sandbox_ok,
        "ok": bool(has_manual_gate and sandbox_ok),
    }


async def main() -> None:
    root = ROOT
    task_file = root / "benchmarks" / "general_capability_tasks.json"
    strategy = run_strategy_benchmark(task_file)
    smoke = await run_capability_smoke(root)
    report = {
        "strategy": strategy,
        "smoke": smoke,
        "overall_ok": bool(strategy.get("score", 0.0) >= 0.75 and smoke.get("ok", False)),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
