from __future__ import annotations

from agentkit.mcp import mcpregistry


def test_reload_mcp_registry_scans_agentkit_even_when_registry_is_not_empty(monkeypatch):
    old_registry = dict(mcpregistry.MCP_REGISTRY)
    old_manifests = dict(mcpregistry.MANIFEST_CACHE)
    old_sources = dict(mcpregistry.MANIFEST_SOURCES)
    try:
        mcpregistry.MCP_REGISTRY.clear()
        mcpregistry.MANIFEST_CACHE.clear()
        mcpregistry.MANIFEST_SOURCES.clear()
        mcpregistry.MCP_REGISTRY["preloaded"] = object()
        monkeypatch.setattr(mcpregistry, "create_service_instance", lambda manifest: object())

        registered = mcpregistry.reload_mcp_registry(["agentkit"])

        assert "computer_control" in registered
        assert "computer_control" in mcpregistry.MCP_REGISTRY
        assert "computer_control" in mcpregistry.MANIFEST_CACHE
        assert "preloaded" in mcpregistry.MCP_REGISTRY
    finally:
        mcpregistry.MCP_REGISTRY.clear()
        mcpregistry.MCP_REGISTRY.update(old_registry)
        mcpregistry.MANIFEST_CACHE.clear()
        mcpregistry.MANIFEST_CACHE.update(old_manifests)
        mcpregistry.MANIFEST_SOURCES.clear()
        mcpregistry.MANIFEST_SOURCES.update(old_sources)
