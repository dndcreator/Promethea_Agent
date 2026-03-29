import pytest

import gateway.app as app_mod


@pytest.mark.asyncio
async def test_health_degraded_when_gateway_not_ready(monkeypatch):
    monkeypatch.setattr(app_mod, "Promethea_agent", object(), raising=False)
    monkeypatch.setattr(app_mod, "gateway_integration", None, raising=False)
    monkeypatch.setattr(app_mod.state, "startup_report", {"status": "failed"}, raising=False)

    out = await app_mod.health_check()
    assert out["status"] == "degraded"
    assert out["gateway_ready"] is False
    assert out["startup_status"] == "failed"


@pytest.mark.asyncio
async def test_health_healthy_when_gateway_running(monkeypatch):
    class _DummyGatewayServer:
        is_running = True

    class _DummyIntegration:
        def get_gateway_server(self):
            return _DummyGatewayServer()

    monkeypatch.setattr(app_mod, "Promethea_agent", object(), raising=False)
    monkeypatch.setattr(app_mod, "gateway_integration", _DummyIntegration(), raising=False)
    monkeypatch.setattr(app_mod.state, "startup_report", {"status": "healthy"}, raising=False)

    out = await app_mod.health_check()
    assert out["status"] == "healthy"
    assert out["gateway_ready"] is True
    assert out["startup_status"] == "healthy"
