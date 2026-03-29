"""
ToolService 
?
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from gateway.tool_service import ToolService, ToolInvocationContext, ToolPolicyViolationError
from gateway.events import EventEmitter


class TestToolService:
    """TODO: add docstring."""
    
    def test_init(self):
        """TODO: add docstring."""
        service = ToolService()
        assert service is not None
        assert service._registered_tools == {}
    
    def test_register_tool(self):
        """TODO: add docstring."""
        service = ToolService()
        
        class TestTool:
            tool_id = "test.tool"
            name = "Test Tool"
            description = "A test tool"
            
            async def invoke(self, args, ctx=None):
                return {"result": "success"}
        
        tool = TestTool()
        service.register_tool(tool)
        assert "test.tool" in service._registered_tools
    
    def test_unregister_tool(self):
        """TODO: add docstring."""
        service = ToolService()
        
        class TestTool:
            tool_id = "test.tool"
            name = "Test Tool"
            description = "A test tool"
            
            async def invoke(self, args, ctx=None):
                return {"result": "success"}
        
        tool = TestTool()
        service.register_tool(tool)
        service.unregister_tool("test.tool")
        assert "test.tool" not in service._registered_tools
    
    @pytest.mark.asyncio
    async def test_list_tools(self):
        """TODO: add docstring."""
        service = ToolService()
        
        # TODO: comment cleaned
        class TestTool:
            tool_id = "test.tool"
            name = "Test Tool"
            description = "A test tool"
            
            async def invoke(self, args, ctx=None):
                return {"result": "success"}
        
        service.register_tool(TestTool())
        
        tools = await service.list_tools()
        assert "tools" in tools
        assert isinstance(tools["tools"], list)
    
    @pytest.mark.asyncio
    async def test_call_tool(self):
        """TODO: add docstring."""
        service = ToolService(event_emitter=EventEmitter())
        
        class TestTool:
            tool_id = "test.tool"
            name = "Test Tool"
            description = "A test tool"
            
            async def invoke(self, args, ctx=None):
                return {"result": "success", "args": args}
        
        tool = TestTool()
        service.register_tool(tool)
        
        result = await service.call_tool(
            "test.tool",
            {"param": "value"},
            ctx=ToolInvocationContext(session_id="test_session")
        )
        
        assert result["result"] == "success"
        assert result["args"]["param"] == "value"


    @pytest.mark.asyncio
    async def test_call_tool_with_run_context_allows_side_effect_by_default(self):
        service = ToolService(event_emitter=EventEmitter())

        class WriteTool:
            tool_id = "local.write_file"
            name = "Write Tool"
            description = "write file"

            async def invoke(self, args, ctx=None):
                return {"ok": True}

        service.register_tool(WriteTool())

        run_context = type("Ctx", (), {"tool_policy": {}, "session_state": type("S", (), {"reasoning_mode": "fast"})()})()

        out = await service.call_tool(
            "local.write_file",
            {"path": "a.txt", "content": "x"},
            ctx=ToolInvocationContext(session_id="s1", user_id="u1"),
            run_context=run_context,
        )
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_call_tool_with_strict_policy_blocks_side_effect_without_allow(self):
        service = ToolService(event_emitter=EventEmitter())

        class WriteTool:
            tool_id = "local.write_file"
            name = "Write Tool"
            description = "write file"

            async def invoke(self, args, ctx=None):
                return {"ok": True}

        service.register_tool(WriteTool())

        run_context = type(
            "Ctx",
            (),
            {
                "tool_policy": {"strict_side_effect_allowlist": True},
                "session_state": type("S", (), {"reasoning_mode": "fast"})(),
            },
        )()

        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool(
                "local.write_file",
                {"path": "a.txt", "content": "x"},
                ctx=ToolInvocationContext(session_id="s1", user_id="u1"),
                run_context=run_context,
            )

    @pytest.mark.asyncio
    async def test_call_tool_without_run_context_keeps_backward_compat(self):
        service = ToolService(event_emitter=EventEmitter())

        class WriteTool:
            tool_id = "local.write_file"
            name = "Write Tool"
            description = "write file"

            async def invoke(self, args, ctx=None):
                return {"ok": True}

        service.register_tool(WriteTool())

        out = await service.call_tool("local.write_file", {"path": "a.txt"})
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_tool_catalog_exposes_callable_now_for_local_and_mcp_health(self):
        class _DummyMCPManager:
            def get_available_services_filtered(self):
                return {
                    "mcp_services": [
                        {
                            "name": "websearch",
                            "description": "web tools",
                            "available_tools": [{"name": "search", "description": "search web"}],
                        }
                    ],
                    "agent_services": [],
                }

            def list_service_health(self, user_id=None):
                _ = user_id
                return [{"service_name": "websearch", "status": "offline", "user_visibility": "visible"}]

        service = ToolService(event_emitter=EventEmitter(), mcp_manager=_DummyMCPManager())

        class LocalTool:
            tool_id = "local.echo"
            name = "Local Echo"
            description = "Echo"

            async def invoke(self, args, ctx=None):
                _ = (args, ctx)
                return {"ok": True}

        service.register_tool(LocalTool())
        catalog = await service.get_tool_catalog()
        by_full = {(row.get("service_name"), row.get("tool_name")): row for row in catalog}
        local_row = by_full.get(("local.echo", "local.echo"))
        assert local_row is not None
        assert local_row.get("callable_now") is True
        assert "requires_confirmation" in local_row

        mcp_row = by_full.get(("websearch", "search"))
        assert mcp_row is not None
        assert mcp_row.get("dependency_ready") is False
        assert mcp_row.get("callable_now") is False

    @pytest.mark.asyncio
    async def test_tool_catalog_callable_now_respects_policy(self):
        service = ToolService(event_emitter=EventEmitter())

        class WriteTool:
            tool_id = "local.write_file"
            name = "Write Tool"
            description = "write file"

            async def invoke(self, args, ctx=None):
                _ = (args, ctx)
                return {"ok": True}

        service.register_tool(WriteTool())
        run_context = type(
            "Ctx",
            (),
            {
                "tool_policy": {"strict_side_effect_allowlist": True},
                "session_state": type("S", (), {"reasoning_mode": "fast"})(),
            },
        )()
        catalog = await service.get_tool_catalog(run_context=run_context, user_config={"tools": {}})
        row = next(
            (
                x
                for x in catalog
                if x.get("service_name") == "local.write_file" and x.get("tool_name") == "local.write_file"
            ),
            None,
        )
        assert row is not None
        assert row.get("policy_allowed") is False
        assert row.get("callable_now") is False

