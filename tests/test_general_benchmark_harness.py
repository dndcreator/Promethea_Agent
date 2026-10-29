from pathlib import Path

import pytest
import json

from scripts.run_general_benchmark import run_capability_smoke, run_strategy_benchmark


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "benchmarks/general_capability_tasks.json").read_text(encoding="utf-8-sig"))["tasks"]


@pytest.fixture(scope="module")
def recommendation_report():
    return run_strategy_benchmark(ROOT / "benchmarks/general_capability_tasks.json")


@pytest.mark.parametrize("case_id", [pytest.param(case["id"], marks=pytest.mark.xfail(reason=case["known_failure"], strict=True))
                                  if case.get("known_failure") else case["id"] for case in CASES])
def test_legacy_rule_recommendation_case(case_id, recommendation_report):
    row = next(row for row in recommendation_report["rows"] if row["id"] == case_id)
    assert row["ok"], row


@pytest.mark.asyncio
async def test_capability_smoke_checks(tmp_path: Path):
    out = await run_capability_smoke(tmp_path)
    assert out["moirai_template_gate"] is True
    assert out["sandbox_guard"] is True
    assert out["workflow_artifact_audit"] is True
    assert out["security_violation_audit"] is True
    assert out["ok"] is True
