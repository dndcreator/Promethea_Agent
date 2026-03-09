from pathlib import Path

import pytest

from scripts.run_general_benchmark import run_capability_smoke, run_strategy_benchmark


def test_strategy_benchmark_score_threshold():
    root = Path(__file__).resolve().parent.parent
    task_file = root / "benchmarks" / "general_capability_tasks.json"
    out = run_strategy_benchmark(task_file)
    assert out["total"] >= 10
    assert out["score"] >= 0.75


@pytest.mark.asyncio
async def test_capability_smoke_checks():
    root = Path(__file__).resolve().parent.parent
    out = await run_capability_smoke(root)
    assert out["moirai_template_gate"] is True
    assert out["sandbox_guard"] is True
    assert out["ok"] is True
