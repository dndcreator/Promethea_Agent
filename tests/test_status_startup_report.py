import pytest

from gateway.http import state
from gateway.http.routes import status


@pytest.mark.asyncio
async def test_status_includes_startup_report(monkeypatch):
    class _MemorySvc:
        def is_enabled(self):
            return True

        def get_sync_stats(self):
            return {"enabled": True, "pending": 0, "queued": 0, "active": 0, "idle": True}

    class _ReasoningSvc:
        def get_stats(self):
            return {"enabled": True, "active_trees": 1}

    class _DummyGateway:
        conversation_service = object()
        memory_service = _MemorySvc()
        reasoning_service = _ReasoningSvc()

    monkeypatch.setattr(status, "get_gateway_server", lambda: _DummyGateway())
    monkeypatch.setattr(
        state,
        "startup_report",
        {"status": "healthy", "components": [], "summary": {"total": 0, "ok": 0, "degraded": 0, "failed": 0}},
        raising=False,
    )

    out = await status.get_status()
    assert out["startup"]["status"] == "healthy"
