from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.http.routes import metrics_config


@pytest.mark.asyncio
async def test_metrics_contains_personal_and_workflow_recovery(monkeypatch):
    class _Workflow:
        def list_runs(self, limit=500):
            _ = limit
            return [
                {"status": "paused"},
                {"status": "failed"},
                {"status": "waiting_human"},
                {"status": "succeeded"},
            ]

    class _Gateway:
        connection_manager = SimpleNamespace(get_active_count=lambda: 1)
        conversation_service = None
        memory_service = None
        channels = {}
        workflow_engine = _Workflow()
        message_manager = SimpleNamespace(
            session={
                "u1::s1": SimpleNamespace(pinned=True),
                "u1::s2": SimpleNamespace(pinned=False),
            }
        )

    monkeypatch.setattr(metrics_config, "get_gateway_server", lambda: _Gateway())
    monkeypatch.setattr(metrics_config.state.metrics, "get_stats", lambda: {"llm": {}, "memory": {}, "sessions": {}, "cost": {}, "uptime_seconds": 0})
    monkeypatch.setattr(metrics_config.user_file_store, "get_global_stats", lambda: {"total_files": 3, "total_bytes": 128, "total_users": 1})

    out = await metrics_config.get_metrics()
    assert out["status"] == "success"
    assert out["metrics"]["personal"]["sessions_current"] == 2
    assert out["metrics"]["personal"]["sessions_pinned"] == 1
    assert out["metrics"]["personal"]["files_total"] == 3
    assert out["metrics"]["workflow_recovery"]["paused"] == 1
    assert out["metrics"]["workflow_recovery"]["failed"] == 1
