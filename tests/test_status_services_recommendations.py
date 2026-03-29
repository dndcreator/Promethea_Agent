import pytest

from gateway.http.routes import status


@pytest.mark.asyncio
async def test_status_services_returns_failed_components_and_recommendations(monkeypatch):
    class _DummyGateway:
        def get_services_health(self):
            return {
                "tool_service": True,
                "memory_service": False,
                "reasoning_service": True,
                "workflow_engine": False,
            }

    monkeypatch.setattr(status, "get_gateway_server", lambda: _DummyGateway())
    out = await status.get_services_status()
    assert out["status"] == "degraded"
    assert out["summary"]["failed"] == 2
    assert set(out["failed_services"]) == {"memory_service", "workflow_engine"}
    assert len(out["recommendations"]) == 2
