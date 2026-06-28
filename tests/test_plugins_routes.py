from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.http.routes import plugins


@pytest.mark.asyncio
async def test_plugins_catalog_returns_schema_and_effective_state(monkeypatch):
    registry = SimpleNamespace(
        plugins=[
            SimpleNamespace(
                id="demo",
                name="Demo Plugin",
                kind=SimpleNamespace(value="service"),
                description="desc",
                version="0.1.0",
                status="loaded",
                enabled=True,
                config_schema={"type": "object", "properties": {"api_key": {"type": "string"}}},
                ui_schema={"fields": [{"key": "api_key", "type": "password"}]},
                capabilities={"modes": ["chat"]},
            )
        ],
        diagnostics=[],
    )

    class _Cfg:
        def get_merged_config(self, user_id):
            _ = user_id
            return {"plugins": {"demo": {"enabled": False, "config": {"api_key": "x"}}}}

    monkeypatch.setattr(plugins, "_require_config_service", lambda: _Cfg())
    monkeypatch.setattr(plugins, "get_active_plugin_registry", lambda: registry)
    monkeypatch.setattr(plugins, "get_gateway_integration", lambda: None)

    out = await plugins.get_plugins_catalog(user_id="u1")
    assert out["status"] == "success"
    assert out["total"] == 1
    row = out["plugins"][0]
    assert row["id"] == "demo"
    assert row["enabled"] is False
    assert row["config"]["api_key"] == "x"
    assert row["configSchema"]["type"] == "object"
    assert row["uiSchema"]["fields"][0]["key"] == "api_key"


@pytest.mark.asyncio
async def test_plugins_validate_reports_type_errors(monkeypatch):
    registry = SimpleNamespace(
        plugins=[
            SimpleNamespace(
                id="demo",
                config_schema={"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"]},
            )
        ],
        diagnostics=[],
    )
    monkeypatch.setattr(plugins, "get_active_plugin_registry", lambda: registry)

    out = await plugins.validate_plugin_config(
        plugins.PluginValidateRequest(plugin_id="demo", config={"enabled": "yes"}),
        user_id="u1",
    )
    assert out["ok"] is False
    assert out["errors"]


@pytest.mark.asyncio
async def test_plugins_apply_updates_user_config_and_refreshes(monkeypatch):
    captured = {}

    class _Cfg:
        async def update_user_config(self, user_id, updates, validate=False):
            captured["user_id"] = user_id
            captured["updates"] = updates
            captured["validate"] = validate
            return {"success": True}

    class _Integration:
        async def maybe_refresh_plugins(self, force=False):
            captured["force"] = force
            return {"ok": True}

    registry = SimpleNamespace(
        plugins=[
            SimpleNamespace(
                id="demo",
                config_schema={"type": "object", "properties": {"k": {"type": "string"}}},
            )
        ],
        diagnostics=[],
    )

    monkeypatch.setattr(plugins, "_require_config_service", lambda: _Cfg())
    monkeypatch.setattr(plugins, "get_active_plugin_registry", lambda: registry)
    monkeypatch.setattr(plugins, "get_gateway_integration", lambda: _Integration())

    out = await plugins.apply_plugin_config(
        plugins.PluginApplyRequest(plugin_id="demo", enabled=True, config={"k": "v"}, validate=True),
        user_id="u1",
    )
    assert out["status"] == "success"
    assert captured["user_id"] == "u1"
    assert captured["updates"]["plugins"]["demo"]["enabled"] is True
    assert captured["updates"]["plugins"]["demo"]["config"]["k"] == "v"
    assert captured["force"] is True


@pytest.mark.asyncio
async def test_extensions_catalog_route_uses_unified_catalog(monkeypatch):
    async def _fake_catalog(*, gateway_server, user_id=None, include_tools=True):
        _ = (gateway_server, include_tools)
        return {"status": "success", "user_id": user_id, "extensions": [{"id": "official.web"}], "total": 1}

    monkeypatch.setattr(plugins, "get_gateway_server", lambda: object())
    monkeypatch.setattr(plugins, "build_extension_catalog", _fake_catalog)

    out = await plugins.get_extensions_catalog(user_id="u1")
    assert out["status"] == "success"
    assert out["total"] == 1
    assert out["extensions"][0]["id"] == "official.web"


@pytest.mark.asyncio
async def test_extensions_reload_route_refreshes_catalog(monkeypatch):
    calls = {"catalog": 0}

    async def _fake_catalog(*, gateway_server, user_id=None, include_tools=True):
        _ = (gateway_server, user_id, include_tools)
        calls["catalog"] += 1
        return {"status": "success", "extensions": [], "total": 0}

    monkeypatch.setattr(plugins, "get_gateway_server", lambda: object())
    monkeypatch.setattr(plugins, "reload_extensions", lambda: {"status": "success", "registered": ["demo"]})
    monkeypatch.setattr(plugins, "build_extension_catalog", _fake_catalog)

    out = await plugins.reload_extension_catalog(user_id="u1")
    assert out["status"] == "success"
    assert out["registered"] == ["demo"]
    assert calls["catalog"] == 1
