from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.http.routes import status


@pytest.mark.asyncio
async def test_status_exposes_workflow_recovery(monkeypatch):
    class _Workflow:
        def list_runs(self, limit=200):
            _ = limit
            return [{"status": "paused"}, {"status": "failed"}, {"status": "waiting_human"}]

    class _Gateway:
        memory_service = None
        conversation_service = object()
        config_service = None
        org_context_service = None
        workflow_engine = _Workflow()

    monkeypatch.setattr(status, "get_gateway_server", lambda: _Gateway())
    out = await status.get_status()
    assert out["status"] == "running"
    assert out["workflow_recovery"]["paused"] == 1
    assert out["workflow_recovery"]["failed"] == 1
    assert out["workflow_recovery"]["waiting_human"] == 1
