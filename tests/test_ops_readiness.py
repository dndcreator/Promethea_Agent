import pytest

from gateway.http import state
from gateway.http.routes import ops


@pytest.mark.asyncio
async def test_ops_readiness_no_go_when_critical_service_down(monkeypatch):
    class _DummyGateway:
        def get_services_health(self):
            return {
                "tool_service": True,
                "conversation_service": False,
                "config_service": True,
                "memory_service": True,
            }

    monkeypatch.setattr(ops, "get_gateway_server", lambda: _DummyGateway())
    monkeypatch.setattr(
        state,
        "startup_report",
        {
            "status": "healthy",
            "components": [],
            "summary": {"total": 0, "ok": 0, "degraded": 0, "failed": 0},
        },
        raising=False,
    )

    out = await ops.ops_readiness()
    readiness = out["readiness"]
    assert readiness["go_no_go"] == "no-go"
    assert "conversation_service" in readiness["critical_failed_services"]


@pytest.mark.asyncio
async def test_ops_readiness_degraded_when_startup_is_degraded(monkeypatch):
    class _DummyGateway:
        def get_services_health(self):
            return {
                "tool_service": True,
                "conversation_service": True,
                "config_service": True,
                "memory_service": True,
            }

    monkeypatch.setattr(ops, "get_gateway_server", lambda: _DummyGateway())
    monkeypatch.setattr(
        state,
        "startup_report",
        {
            "status": "degraded",
            "components": [{"name": "mcp_registry", "status": "degraded", "detail": "offline"}],
            "summary": {"total": 1, "ok": 0, "degraded": 1, "failed": 0},
        },
        raising=False,
    )

    out = await ops.ops_readiness()
    readiness = out["readiness"]
    assert readiness["go_no_go"] == "go"
    assert readiness["level"] == "degraded"
    assert readiness["startup_status"] == "degraded"
