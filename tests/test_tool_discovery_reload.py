from __future__ import annotations

import json

import pytest

from agentkit.mcp import mcpregistry
from gateway.capability_service import CapabilityService


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
    _write_manifest(package, [{"command": "ping", "sideEffectLevel": "read_only"}])

    service = CapabilityService()
    registered = service.reload_discovered_tools([str(tmp_path)], reload_modules=False)
    assert registered == ["demo_dynamic.ping"]
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
        "capabilities": {"invocation_commands": []},
    }
    (tmp_path / "agent-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        registered = mcpregistry.reload_mcp_registry([str(tmp_path)])
        assert registered == ["demo_external"]
        assert mcpregistry.MCP_REGISTRY["demo_external"]["command"] == "node"
        assert mcpregistry.MCP_REGISTRY["demo_external"]["args"] == ["server.js"]
    finally:
        mcpregistry.MCP_REGISTRY.clear()
        mcpregistry.MCP_REGISTRY.update(old_registry)
        mcpregistry.MANIFEST_CACHE.clear()
        mcpregistry.MANIFEST_CACHE.update(old_manifests)
        mcpregistry.MANIFEST_SOURCES.clear()
        mcpregistry.MANIFEST_SOURCES.update(old_sources)
