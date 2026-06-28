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

    @pytest.mark.asyncio
    async def test_call_tool_normalizes_swapped_mcp_call_before_execution(self):
        class _DummyMCPManager:
            def get_available_services_filtered(self):
                return {
                    "mcp_services": [
                        {
                            "name": "computer_control",
                            "description": "computer tools",
                            "available_tools": [{"name": "execute_command", "description": "run command"}],
                        }
                    ],
                    "agent_services": [],
                }

            async def unified_call(self, service_name, tool_name, args):
                return {"service_name": service_name, "tool_name": tool_name, "args": args}

        service = ToolService(event_emitter=EventEmitter(), mcp_manager=_DummyMCPManager())
        out = await service.call_tool(
            "computer_control",
            {
                "agentType": "local",
                "service_name": "execute_command",
                "command": "echo hello",
            },
        )

        assert out["service_name"] == "computer_control"
        assert out["tool_name"] == "execute_command"
        assert out["args"]["command"] == "echo hello"


    @pytest.mark.asyncio
    async def test_tool_hooks_are_invoked_on_success_and_error(self):
        class _HookMgr:
            def __init__(self):
                self.before = 0
                self.after = 0
                self.error = 0

            async def before_tool_call(self, payload):
                _ = payload
                self.before += 1
                return payload

            async def after_tool_call(self, payload):
                _ = payload
                self.after += 1
                return payload

            async def on_tool_error(self, payload):
                _ = payload
                self.error += 1
                return payload

        class OkTool:
            tool_id = "local.ok"
            name = "ok"
            description = "ok"

            async def invoke(self, args, ctx=None):
                _ = (args, ctx)
                return {"ok": True}

        class BadTool:
            tool_id = "local.bad"
            name = "bad"
            description = "bad"

            async def invoke(self, args, ctx=None):
                _ = (args, ctx)
                raise RuntimeError("boom")

        hooks = _HookMgr()
        service = ToolService(event_emitter=EventEmitter(), hook_manager=hooks)
        service.register_tool(OkTool())
        service.register_tool(BadTool())

        out = await service.call_tool("local.ok", {"x": 1})
        assert out["ok"] is True

        with pytest.raises(RuntimeError):
            await service.call_tool("local.bad", {"x": 1})

        assert hooks.before == 2
        assert hooks.after == 1
        assert hooks.error == 1

    @pytest.mark.asyncio
    async def test_tool_events_include_tenant_and_environment_from_run_context(self):
        service = ToolService(event_emitter=EventEmitter())

        class EchoTool:
            tool_id = "local.echo_ctx"
            name = "echo_ctx"
            description = "echo"

            async def invoke(self, args, ctx=None):
                _ = (args, ctx)
                return {"ok": True}

        service.register_tool(EchoTool())

        captured = []

        async def _capture(event_type, payload):
            captured.append((event_type, payload))

        service._emit_event = AsyncMock(side_effect=_capture)
        run_context = type(
            "Ctx",
            (),
            {
                "trace_id": "trace_1",
                "request_id": "req_1",
                "session_state": type(
                    "S",
                    (),
                    {
                        "session_id": "s1",
                        "user_id": "u1",
                        "trace_id": "trace_1",
                        "tenant_id": "tenant_a",
                        "environment": "prod",
                    },
                )(),
            },
        )()

        out = await service.call_tool(
            "local.echo_ctx",
            {"x": 1},
            run_context=run_context,
            ctx=ToolInvocationContext(session_id="s1", user_id="u1"),
        )
        assert out["ok"] is True
        start_payload = captured[0][1]
        assert start_payload.get("tenant_id") == "tenant_a"
        assert start_payload.get("environment") == "prod"
