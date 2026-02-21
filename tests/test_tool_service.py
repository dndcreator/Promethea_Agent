"""
ToolService 
?
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from gateway.tool_service import ToolService, ToolInvocationContext
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

