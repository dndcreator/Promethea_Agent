import pytest

from gateway.http.routes.ops import ops_governance


@pytest.mark.asyncio
async def test_ops_governance_exposes_runtime_contracts():
    payload = await ops_governance()
    assert payload["status"] == "success"
    governance = payload.get("governance") or {}
    contracts = governance.get("contracts") or {}
    assert contracts.get("task_graph", {}).get("version") == "1.0"
    assert contracts.get("orchestration", {}).get("version") == "1.0"
    assert contracts.get("context_budget", {}).get("version") == "1.0"
    assert payload.get("generated_at")
