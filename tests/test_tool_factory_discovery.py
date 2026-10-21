import json
import sys
import textwrap
from types import SimpleNamespace

import pytest

from gateway.capability_service import CapabilityService, ToolInvocationContext, ToolCapabilityUnavailableError
from gateway.tools.spec import ToolSource


def _package(root, monkeypatch, name="factory_demo"):
    package = root / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "tools.py").write_text(textwrap.dedent('''
        class EchoTool:
            tool_id = "demo.echo"
            name = tool_id
            description = "Read the supplied value"
            domain = "demo"
            input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}
            side_effect_level = "read_only"
            concurrency_safe = True
            presentation = {"title": "Read value", "subject_arg": "value"}

            def __init__(self, dependency):
                self.dependency = dependency

            def check_ready(self, user_id):
                return (user_id == "alice", "account_unavailable")

            async def invoke(self, args, ctx=None):
                return {"value": args["value"], "dependency": self.dependency}

        def create_tools(runtime):
            return [EchoTool(runtime.get("dependency"))]
    '''), encoding="utf-8")
    manifest = {
        "name": name, "serviceType": "tool", "version": "1.0.0",
        "entryPoint": {"module": f"{name}.tools", "factory": "create_tools"},
    }
    path = package / "agent-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.syspath_prepend(str(root))
    return package, path, manifest


@pytest.mark.parametrize("location", ["bundled", "installed"])
@pytest.mark.asyncio
async def test_factory_packages_share_registry_readiness_policy_and_schema(tmp_path, monkeypatch, location):
    root = tmp_path / location
    _package(root, monkeypatch, name=f"factory_{location}")
    service = CapabilityService()
    dependency = object()
    service.bind_tool_runtime(dependency=dependency)
    service.reload_discovered_tools([str(root)], reload_modules=False)
    spec = service.tool_registry.resolve(tool_name="demo.echo", params={})
    assert spec.source is ToolSource.EXTENSION
    assert spec.input_schema["properties"]["value"] == {"type": "string"}
    assert spec.concurrency_safe is True
    assert spec.presentation["title"] == "Read value"
    assert service.requires_confirmation("demo.echo", {}) is False
    assert not hasattr(service._registered_tools["demo.echo"], "official")
    for user, ready in (("alice", True), ("bob", False)):
        ctx = ToolInvocationContext(user_id=user)
        catalog = await service.get_tool_catalog(run_context=ctx)
        assert catalog[0]["callable_now"] is ready
        assert service.inspect_capabilities(["demo.echo"], run_context=ctx)["items"][0]["callable_now"] is ready
    result = await service.call_tool("demo.echo", {"value": "one"}, ctx=ToolInvocationContext(user_id="alice"))
    assert result == {"value": "one", "dependency": dependency}


@pytest.mark.asyncio
async def test_factory_reload_refreshes_code_and_removes_deleted_tools(tmp_path, monkeypatch):
    package, manifest, _ = _package(tmp_path, monkeypatch, name="factory_refresh")
    service = CapabilityService()
    service.reload_discovered_tools([str(tmp_path)], reload_modules=False)
    source = package / "tools.py"
    source.write_text(source.read_text(encoding="utf-8").replace('"value": args["value"]', '"value": "updated:" + args["value"]'), encoding="utf-8")
    service.reload_discovered_tools([str(tmp_path)])
    result = await service.call_tool("demo.echo", {"value": "two"}, ctx=ToolInvocationContext(user_id="alice"))
    assert result["value"] == "updated:two"
    manifest.unlink()
    assert service.reload_discovered_tools([str(tmp_path)]) == []
    assert "demo.echo" not in service._registered_tools
    assert "demo.echo" not in {spec.full_name for spec in service.tool_registry.list_specs()}


@pytest.mark.parametrize("replacement", [
    'return [object()]',
    'return [EchoTool(None), EchoTool(None)]',
    'return [type("Bad", (EchoTool,), {"presentation": {"unknown": True}})(None)]',
    'return "not a tool list"',
])
def test_invalid_factory_snapshot_leaves_live_registry_unchanged(tmp_path, monkeypatch, replacement):
    package, _, _ = _package(tmp_path, monkeypatch, name=f"factory_invalid_{abs(hash(replacement))}")
    service = CapabilityService()
    service.reload_discovered_tools([str(tmp_path)], reload_modules=False)
    original = service._registered_tools["demo.echo"]
    source = package / "tools.py"
    source.write_text(source.read_text(encoding="utf-8").replace('return [EchoTool(runtime.get("dependency"))]', replacement), encoding="utf-8")
    with pytest.raises(ValueError):
        service.reload_discovered_tools([str(tmp_path)])
    assert service._registered_tools["demo.echo"] is original
    assert service.tool_registry.resolve(tool_name="demo.echo", params={}).presentation["title"] == "Read value"


def test_bundled_factory_tracks_host_service_replacement_without_duplicate_registration():
    service = CapabilityService()
    service.ensure_discovered_tools()
    assert "memory.get_context" not in service._registered_tools
    first_memory = object()
    service.bind_tool_runtime(memory_service=first_memory)
    service.ensure_discovered_tools()
    assert service._registered_tools["memory.get_context"].memory_service is first_memory
    original = service._registered_tools["memory.get_context"]
    service.bind_tool_runtime(memory_service=first_memory)
    service.ensure_discovered_tools()
    assert service._registered_tools["memory.get_context"] is original
    second_memory = object()
    service.bind_tool_runtime(memory_service=second_memory)
    service.ensure_discovered_tools()
    assert service._registered_tools["memory.get_context"].memory_service is second_memory
    service.bind_tool_runtime(memory_service=None)
    service.ensure_discovered_tools()
    assert "memory.get_context" not in service._registered_tools
    assert "memory.get_context" not in {spec.full_name for spec in service.tool_registry.list_specs()}


@pytest.mark.asyncio
async def test_runtime_inspection_includes_mcp_and_native_tools_without_origin_filter():
    manager = SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": [{
        "name": "remote", "available_tools": [{"name": "lookup", "side_effect_level": "read_only"}],
    }]})
    service = CapabilityService(mcp_manager=manager)
    service.bind_tool_runtime(gateway_server=SimpleNamespace(capability_service=service))
    service.ensure_discovered_tools()
    tools = await service.call_tool("runtime.list_tools", {})
    ids = {row["tool_id"] for row in tools["tools"]}
    assert {"web.search", "mail.search", "remote.lookup"} <= ids
    selected = await service.call_tool("runtime.list_tools", {"tool_id": "remote.lookup"})
    assert selected["count"] == 1
    assert selected["tools"][0]["tool_id"] == "remote.lookup"


def test_full_reload_preserves_standard_tool_ids_and_refreshes_native_implementations():
    service = CapabilityService()
    before_ids = set(service.ensure_discovered_tools())
    before_tool = service._registered_tools["web.search"]
    modules = [module for name, module in list(sys.modules.items()) if name.startswith("agentkit.tools.") and module is not None]
    snapshots = [(module, vars(module).copy()) for module in modules]
    try:
        after_ids = set(service.reload_discovered_tools())
        assert after_ids == before_ids
        assert service._registered_tools["web.search"] is not before_tool
        assert type(service._registered_tools["web.search"]) is not type(before_tool)
        assert service.tool_registry.resolve(tool_name="mail.send", params={}).input_schema["type"] == "object"
        assert service.requires_confirmation("mail.send", {}) is True
    finally:
        # Reload rebinds exported Python classes; do not leak them to other tests.
        for module, namespace in snapshots:
            vars(module).clear()
            vars(module).update(namespace)


@pytest.mark.asyncio
async def test_extension_catalog_respects_owner_visibility_and_shared_readiness():
    from gateway.extension_catalog import build_extension_catalog

    manager = SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": [{
        "name": "remote", "available_tools": [{
            "name": "private", "side_effect_level": "read_only", "owner_user_id": "alice",
        }],
    }]})
    service = CapabilityService(mcp_manager=manager)
    server = SimpleNamespace(
        capability_service=service, ensure_capability_service=lambda: service,
    )

    class PrivateTool:
        tool_id = "private.read"
        name = tool_id
        description = "Read a private record"
        side_effect_level = "read_only"
        owner_user_id = "alice"

        async def invoke(self, args, ctx=None):
            return {}

    service.register_tool(PrivateTool())
    for user, visible in (("alice", True), ("bob", False)):
        result = await build_extension_catalog(gateway_server=server, user_id=user)
        tools = {tool["tool_id"]: tool for pack in result["extensions"] for tool in pack["tools"]}
        assert ("private.read" in tools) is visible
        assert ("remote.private" in tools) is visible
        assert set(result["roots"]) == {"bundled", "community"}
        standard = next(pack for pack in result["extensions"] if pack["id"] == "standard")
        assert standard["provider"] == "plugin"
        assert "mail.search" in tools
        scope = ToolInvocationContext(user_id=user)
        row = next(item for item in await service.get_tool_catalog(run_context=scope) if item["tool_name"] == "mail.search")
        assert tools["mail.search"]["callable_now"] == row["callable_now"]


@pytest.mark.asyncio
async def test_mcp_collision_does_not_duplicate_catalog_or_downgrade_native_permissions():
    from unittest.mock import AsyncMock

    providers = {"mcp_services": [{
        "name": "remote", "available_tools": [{"name": "lookup", "side_effect_level": "read_only"}],
    }]}
    manager = SimpleNamespace(
        get_available_services_filtered=lambda: providers,
        call_service_tool=AsyncMock(return_value={"ok": True}),
    )
    service = CapabilityService(mcp_manager=manager)
    service.ensure_discovered_tools()
    await service.get_tool_catalog()
    providers["mcp_services"].append({
        "name": "mail", "available_tools": [{"name": "send", "side_effect_level": "read_only"}],
    })
    catalog = await service.get_tool_catalog()
    send = [row for row in catalog if row["tool_name"] == "mail.send"]
    assert len(send) == 1
    assert send[0]["requires_confirmation"] is True
    assert service.requires_confirmation("mail.send", {}) is True
    remote = next(row for row in catalog if row["service_name"] == "remote")
    assert remote["callable_now"] is False
    assert remote["callable_reason"] == "mcp_registry_refresh_failed"
    with pytest.raises(ToolCapabilityUnavailableError, match="mcp_registry_refresh_failed"):
        await service.call_tool("remote.lookup", {})
    manager.call_service_tool.assert_not_awaited()
    assert await service.call_tool("text.word_stats", {"text": "hello"})
    providers["mcp_services"].pop()
    catalog = await service.get_tool_catalog()
    assert next(row for row in catalog if row["service_name"] == "remote")["callable_now"] is True
    assert service._mcp_registry_error is None


def test_failed_native_registration_cannot_leave_an_execution_without_matching_spec():
    from gateway.tools.spec import ToolSpec

    service = CapabilityService()
    spec = ToolSpec(tool_name="echo", service_name="demo", source=ToolSource.MCP)
    service.tool_registry.register_spec(spec)
    tool = SimpleNamespace(tool_id="demo.echo", name="echo", description="Echo", invoke=lambda args: args)
    with pytest.raises(ValueError, match="another execution source"):
        service.register_tool(tool)
    assert "demo.echo" not in service._registered_tools
    assert service.tool_registry.resolve(tool_name="demo.echo", params={}) is spec


def test_factory_cannot_replace_an_active_mcp_binding(tmp_path, monkeypatch):
    from gateway.tools.spec import ToolSpec

    _package(tmp_path, monkeypatch, name="factory_mcp_collision")
    service = CapabilityService()
    spec = ToolSpec(tool_name="echo", service_name="demo", source=ToolSource.MCP)
    service.tool_registry.register_spec(spec)
    with pytest.raises(ValueError, match="another execution source"):
        service.reload_discovered_tools([str(tmp_path)], reload_modules=False)
    assert service._registered_tools == {}
    assert service._discovered_tool_sources == {}
    assert service.tool_registry.resolve(tool_name="demo.echo", params={}) is spec
