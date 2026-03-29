from types import SimpleNamespace

import pytest

from gateway.http.routes import doctor


@pytest.mark.asyncio
async def test_doctor_includes_summary_and_recommendations(monkeypatch):
    fake_cfg = SimpleNamespace(
        api=SimpleNamespace(api_key="", base_url="https://x", model="m"),
        memory=SimpleNamespace(
            enabled=True,
            neo4j=SimpleNamespace(enabled=True, uri="bolt://127.0.0.1:7687"),
            warm_layer=SimpleNamespace(enabled=True),
        ),
    )
    monkeypatch.setattr(doctor.config_module, "config", fake_cfg, raising=False)

    class _DummyGateway:
        is_running = True
        channels = {}
        connection_manager = SimpleNamespace(get_active_count=lambda: 0)
        message_manager = SimpleNamespace(session={})
        memory_service = None

    monkeypatch.setattr(doctor, "get_gateway_server", lambda: _DummyGateway())

    class _DummyRegistry:
        plugins = []
        channels = []
        services = []

    import core.plugins.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "get_active_plugin_registry", lambda: _DummyRegistry())
    monkeypatch.setattr(doctor.state.metrics, "get_stats", lambda: {"events": 0})

    out = await doctor.run_doctor()
    assert out["status"] in {"degraded", "unhealthy"}
    assert "summary" in out
    assert out["summary"]["checks_total"] >= out["summary"]["checks_ok"]
    assert isinstance(out.get("recommendations"), list)
    assert any(item.get("component") == "config_api" for item in out.get("recommendations", []))


@pytest.mark.asyncio
async def test_doctor_sessions_inventory_supports_sessions_attr(monkeypatch):
    fake_cfg = SimpleNamespace(
        api=SimpleNamespace(api_key="x", base_url="https://x", model="m"),
        memory=SimpleNamespace(
            enabled=False,
            neo4j=SimpleNamespace(enabled=False, uri="bolt://127.0.0.1:7687"),
            warm_layer=SimpleNamespace(enabled=False),
        ),
    )
    monkeypatch.setattr(doctor.config_module, "config", fake_cfg, raising=False)

    class _DummyGateway:
        is_running = True
        channels = {}
        connection_manager = SimpleNamespace(get_active_count=lambda: 0)
        # no `session` attr, only `sessions` attr
        message_manager = SimpleNamespace(sessions={"a": {}, "b": {}})
        memory_service = None

    monkeypatch.setattr(doctor, "get_gateway_server", lambda: _DummyGateway())

    class _DummyRegistry:
        plugins = []
        channels = []
        services = []

    import core.plugins.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "get_active_plugin_registry", lambda: _DummyRegistry())
    monkeypatch.setattr(doctor.state.metrics, "get_stats", lambda: {"events": 0})

    out = await doctor.run_doctor()
    assert out["checks"]["sessions"]["status"] == "ok"
    assert out["checks"]["sessions"]["sessions_in_memory"] == 2
