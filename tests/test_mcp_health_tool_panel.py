from types import SimpleNamespace

import pytest

from agentkit.mcp import mcp_manager as mcp_manager_module
from agentkit.mcp.mcp_manager import MCPManager
from agentkit.mcp.mcpregistry import MANIFEST_CACHE, MCP_REGISTRY
from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer


@pytest.fixture
def isolated_mcp_registry():
    old_registry = dict(MCP_REGISTRY)
    old_manifest = dict(MANIFEST_CACHE)
    MCP_REGISTRY.clear()
    MANIFEST_CACHE.clear()
    try:
        yield
    finally:
        MCP_REGISTRY.clear()
        MCP_REGISTRY.update(old_registry)
        MANIFEST_CACHE.clear()
        MANIFEST_CACHE.update(old_manifest)


def _register_service(name: str, *, visibility=None):
    MCP_REGISTRY[name] = {
        "transport": "stdio",
        "command": "node",
        "args": ["server.js"],
        "cwd": None,
        "env": {},
    }
    MANIFEST_CACHE[name] = {
        "name": name,
        "label": name,
        "version": "1.0.0",
        "description": f"{name} service",
        "capabilities": {
            "invocation_commands": [
                {"command": "echo", "description": "Echo text"},
            ]
        },
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "visibility": visibility or {"public": True},
    }


@pytest.mark.asyncio
async def test_external_service_health_snapshot_defaults_unknown(isolated_mcp_registry):
    _register_service("svc_a")
    manager = MCPManager()

    rows = manager.list_service_health(user_id="u1")

    assert len(rows) == 1
    assert rows[0]["service_name"] == "svc_a"
    assert rows[0]["status"] == "unknown"
    assert rows[0]["source"] == "registry"
    assert rows[0]["user_visibility"] == "visible"


@pytest.mark.asyncio
async def test_remote_service_health_snapshot_defaults_unknown(isolated_mcp_registry):
    MCP_REGISTRY["svc_remote"] = {"transport": "stdio", "command": "python", "args": ["remote.py"]}
    MANIFEST_CACHE["svc_remote"] = {
        "name": "svc_remote",
        "label": "svc_remote",
        "capabilities": {"invocation_commands": []},
        "visibility": {"public": True},
    }
    manager = MCPManager()

    rows = manager.list_service_health(user_id="u1")

    assert rows[0]["status"] == "unknown"
    assert rows[0]["source"] == "registry"


@pytest.mark.asyncio
async def test_service_online_after_tool_sync(isolated_mcp_registry):
    _register_service("svc_a")
    manager = MCPManager()
    manager.tools_cache["svc_a"] = [{"name": "echo", "description": "Echo text"}]

    tools = await manager.get_service_tools_async("svc_a")
    health = manager.get_service_health("svc_a", user_id="u1")

    assert len(tools) == 1
    assert health["status"] == "online"
    assert health["tool_count"] == 1
    assert health["last_sync_at"]


@pytest.mark.asyncio
async def test_external_provider_tools_are_discovered_into_catalog(isolated_mcp_registry, monkeypatch):
    _register_service("svc_external")
    manager = MCPManager()

    class _Session:
        async def list_tools(self):
            return SimpleNamespace(
                tools=[SimpleNamespace(
                    name="lookup",
                    description="Look up a record",
                    inputSchema={"type": "object", "properties": {"id": {"type": "string"}}},
                )]
            )

    async def _connect(service_name):
        assert service_name == "svc_external"
        return _Session()

    monkeypatch.setattr(manager, "connect_service", _connect)
    await manager.refresh_registered_tools()
    services = manager.get_available_services_filtered()["mcp_services"]
    tools = services[0]["available_tools"]
    assert tools[0]["name"] == "lookup"
    assert tools[0]["input_schema"]["properties"]["id"]["type"] == "string"


@pytest.mark.asyncio
async def test_tool_listing_builds_descriptor(isolated_mcp_registry):
    _register_service("svc_a")
    manager = MCPManager()
    manager.tools_cache["svc_a"] = [{
        "name": "echo",
        "description": "Echo text",
        "input_schema": MANIFEST_CACHE["svc_a"]["inputSchema"],
    }]

    rows = await manager.list_tool_descriptors(service_name="svc_a", user_id="u1")

    assert len(rows) == 1
    row = rows[0]
    assert row["service_name"] == "svc_a"
    assert row["tool_name"] == "echo"
    assert row["input_schema_summary"]["type"] == "object"
    assert "text" in row["input_schema_summary"]["properties"]


@pytest.mark.asyncio
async def test_last_error_persisted_in_health_snapshot(isolated_mcp_registry, monkeypatch):
    MCP_REGISTRY["svc_remote"] = {"transport": "stdio", "command": "python", "args": ["missing_script.py"]}
    MANIFEST_CACHE["svc_remote"] = {
        "name": "svc_remote",
        "label": "svc_remote",
        "capabilities": {"invocation_commands": []},
        "visibility": {"public": True},
    }
    manager = MCPManager()

    monkeypatch.setattr(mcp_manager_module, "MCP_CLIENT_AVAILABLE", False)
    await manager.get_service_tools_async("svc_remote")
    health = manager.get_service_health("svc_remote", user_id="u1")

    assert health["status"] == "degraded"
    assert "unavailable" in str(health["last_error"]).lower()


@pytest.mark.asyncio
async def test_user_visibility_filter(isolated_mcp_registry):
    _register_service("svc_public", visibility={"public": True})
    _register_service("svc_private", visibility={"users": ["u_allow"]})
    manager = MCPManager()
    manager.tools_cache["svc_public"] = [{"name": "echo"}]
    manager.tools_cache["svc_private"] = [{"name": "echo"}]

    rows_for_blocked = await manager.list_visible_tools_for_user("u_blocked")
    rows_for_allowed = await manager.list_visible_tools_for_user("u_allow")

    blocked_services = {row["service_name"] for row in rows_for_blocked}
    allowed_services = {row["service_name"] for row in rows_for_allowed}

    assert "svc_public" in blocked_services
    assert "svc_private" not in blocked_services
    assert "svc_private" in allowed_services


@pytest.mark.asyncio
async def test_gateway_mcp_panel_handlers(isolated_mcp_registry):
    _register_service("svc_panel")
    manager = MCPManager()
    manager.tools_cache["svc_panel"] = [{"name": "echo"}]
    server = GatewayServer()
    server.mcp_manager = manager

    connection = SimpleNamespace(connection_id="c1", identity=None)

    res_services = await server._handle_mcp_services_list(
        connection,
        RequestMessage(id="r1", method=RequestType.MCP_SERVICES_LIST, params={"user_id": "u1"}),
    )
    res_tools = await server._handle_mcp_visible_tools(
        connection,
        RequestMessage(id="r2", method=RequestType.MCP_VISIBLE_TOOLS, params={"user_id": "u1"}),
    )

    assert res_services.ok is True
    assert res_services.payload["total"] == 1
    assert res_tools.ok is True
    assert res_tools.payload["total"] >= 1
