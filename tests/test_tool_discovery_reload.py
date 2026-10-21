from __future__ import annotations

import json

import pytest

from agentkit.mcp import mcpregistry
from gateway.capability_service import CapabilityService


@pytest.fixture
def isolated_mcp_config():
    tables = [mcpregistry.MCP_REGISTRY, mcpregistry.MANIFEST_CACHE, mcpregistry.MANIFEST_SOURCES]
    snapshots = [dict(table) for table in tables]
    for table in tables:
        table.clear()
    try:
        yield
    finally:
        for table, snapshot in zip(tables, snapshots):
            table.clear()
            table.update(snapshot)


def _external_manifest(root, name, command="python"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "agent-manifest.json"
    payload = {"name": name, "serviceType": "mcp", "transport": {"type": "stdio", "command": command, "args": []}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_mcp_config_reload_is_atomic_and_preserves_unselected_roots(tmp_path, isolated_mcp_config):
    selected = tmp_path / "selected"
    unrelated = tmp_path / "unrelated"
    first = _external_manifest(selected, "selected_provider")
    _external_manifest(unrelated, "other_provider")
    mcpregistry.reload_mcp_registry([str(selected), str(unrelated)])
    tables = [mcpregistry.MCP_REGISTRY, mcpregistry.MANIFEST_CACHE, mcpregistry.MANIFEST_SOURCES]
    before = [dict(table) for table in tables]
    _external_manifest(selected, "selected_provider", command="")
    with pytest.raises(ValueError, match="command and args"):
        mcpregistry.reload_mcp_registry([str(selected)])
    assert [dict(table) for table in tables] == before
    _external_manifest(selected, "selected_provider", command="node")
    assert mcpregistry.reload_mcp_registry([str(selected)]) == ["selected_provider"]
    assert mcpregistry.MCP_REGISTRY["selected_provider"]["command"] == "node"
    assert mcpregistry.MCP_REGISTRY["other_provider"] == before[0]["other_provider"]
    first.unlink()
    assert mcpregistry.reload_mcp_registry([str(selected)]) == []
    assert set(mcpregistry.MCP_REGISTRY) == {"other_provider"}


def test_mcp_config_rejects_duplicate_names_and_deduplicates_overlapping_roots(tmp_path, isolated_mcp_config):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _external_manifest(first, "provider")
    assert mcpregistry.reload_mcp_registry([str(tmp_path), str(first)]) == ["provider"]
    original = dict(mcpregistry.MCP_REGISTRY)
    _external_manifest(second, "provider")
    with pytest.raises(ValueError, match="duplicate MCP provider"):
        mcpregistry.reload_mcp_registry([str(tmp_path)])
    assert mcpregistry.MCP_REGISTRY == original
    with pytest.raises(ValueError, match="duplicate MCP provider"):
        mcpregistry.reload_mcp_registry([str(second)])
    assert mcpregistry.MCP_REGISTRY == original


def test_mcp_config_does_not_register_native_entrypoints(tmp_path, isolated_mcp_config):
    payload = {"name": "native", "serviceType": "mcp", "entryPoint": {"module": "native", "class": "Service"}}
    (tmp_path / "agent-manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert mcpregistry.reload_mcp_registry([str(tmp_path)]) == []
    assert not mcpregistry.MCP_REGISTRY


@pytest.mark.asyncio
async def test_bad_mcp_config_does_not_close_existing_connections(tmp_path, isolated_mcp_config, monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from gateway import extension_catalog

    root = tmp_path / "plugins"
    _external_manifest(root, "broken", command="")
    manager = SimpleNamespace(clean_services=AsyncMock())
    service = SimpleNamespace(reload_discovered_tools=lambda *args, **kwargs: [])
    monkeypatch.setattr(extension_catalog, "BUNDLED_TOOL_ROOT", root)
    monkeypatch.setattr(extension_catalog, "COMMUNITY_EXTENSION_ROOT", tmp_path / "community")
    monkeypatch.setattr(extension_catalog, "ensure_capability_service", lambda server: service)
    monkeypatch.setattr(extension_catalog, "get_mcp_manager", lambda: manager)
    with pytest.raises(ValueError):
        await extension_catalog.reload_extensions(object())
    manager.clean_services.assert_not_awaited()


def _write_manifest(root, commands):
    manifest = {
        "name": "demo_dynamic",
        "label": "Demo Dynamic",
        "version": "1.0.0",
        "serviceType": "extension_tool",
        "entryPoint": {"module": "demo_package.tool", "class": "DemoService"},
        "capabilities": {"invocation_commands": commands},
        "inputSchema": {"type": "object", "additionalProperties": True},
    }
    path = root / "agent-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.asyncio
async def test_manifest_tools_auto_register_and_hot_reload(tmp_path, monkeypatch):
    package = tmp_path / "demo_package"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "tool.py").write_text(
        "class DemoService:\n"
        "    async def ping(self, value='ping'):\n"
        "        return {'value': value}\n"
        "    async def pong(self, value='pong'):\n"
        "        return {'value': value}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    _write_manifest(package, [{
        "command": "ping",
        "sideEffectLevel": "read_only",
        "presentation": {"title": "Ping service", "subject_arg": "value"},
    }])

    service = CapabilityService()
    registered = service.reload_discovered_tools([str(tmp_path)], reload_modules=False)
    assert registered == ["demo_dynamic.ping"]
    assert service.tool_registry.resolve(tool_name="demo_dynamic.ping", params={}).presentation["title"] == "Ping service"
    assert await service.call_tool("demo_dynamic.ping", {"value": "first"}) == {"value": "first"}

    _write_manifest(package, [{"command": "missing", "sideEffectLevel": "read_only"}])
    with pytest.raises(AttributeError, match="missing method"):
        service.reload_discovered_tools([str(tmp_path)], reload_modules=True)
    assert "demo_dynamic.ping" in service._registered_tools

    _write_manifest(package, [{"command": "pong", "sideEffectLevel": "read_only"}])
    reloaded = service.reload_discovered_tools([str(tmp_path)], reload_modules=True)
    assert reloaded == ["demo_dynamic.pong"]
    assert "demo_dynamic.ping" not in service._registered_tools
    assert await service.call_tool("demo_dynamic.pong", {"value": "second"}) == {"value": "second"}


def test_external_mcp_manifest_scan_registers_transport_only(tmp_path):
    old_registry = dict(mcpregistry.MCP_REGISTRY)
    old_manifests = dict(mcpregistry.MANIFEST_CACHE)
    old_sources = dict(mcpregistry.MANIFEST_SOURCES)
    manifest = {
        "name": "demo_external",
        "serviceType": "mcp",
        "transport": {
            "type": "stdio",
            "command": "node",
            "args": ["server.js"],
            "env": {"TOKEN": "${DEMO_TOKEN}"},
        },
        "capabilities": {"invocation_commands": [{
            "command": "lookup",
            "presentation": {"title": "Lookup record", "subject_arg": "query"},
        }]},
    }
    (tmp_path / "agent-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        registered = mcpregistry.reload_mcp_registry([str(tmp_path)])
        assert registered == ["demo_external"]
        assert mcpregistry.MCP_REGISTRY["demo_external"]["command"] == "node"
        assert mcpregistry.MCP_REGISTRY["demo_external"]["args"] == ["server.js"]
        assert mcpregistry.get_available_tools("demo_external")[0]["presentation"]["title"] == "Lookup record"
    finally:
        mcpregistry.MCP_REGISTRY.clear()
        mcpregistry.MCP_REGISTRY.update(old_registry)
        mcpregistry.MANIFEST_CACHE.clear()
        mcpregistry.MANIFEST_CACHE.update(old_manifests)
        mcpregistry.MANIFEST_SOURCES.clear()
        mcpregistry.MANIFEST_SOURCES.update(old_sources)


def test_manifest_tool_rejects_invalid_presentation(tmp_path, monkeypatch):
    package = tmp_path / "invalid_presentation"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "tool.py").write_text(
        "class DemoService:\n"
        "    async def ping(self, value='ping'):\n"
        "        return {'value': value}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest = {
        "name": "invalid_presentation",
        "serviceType": "extension_tool",
        "entryPoint": {"module": "invalid_presentation.tool", "class": "DemoService"},
        "capabilities": {"invocation_commands": [{
            "command": "ping",
            "presentation": {"title": "Ping", "unknown": True},
        }]},
    }
    (package / "agent-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        CapabilityService().reload_discovered_tools([str(tmp_path)], reload_modules=False)
