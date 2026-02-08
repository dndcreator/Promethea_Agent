"""
ToolService 测试
测试工具服务的核心功能
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from gateway.tool_service import ToolService, ToolInvocationContext
from gateway.events import EventEmitter


class TestToolService:
    """ToolService 测试类"""
    
    def test_init(self):
        """测试初始化"""
        service = ToolService()
        assert service is not None
        assert service._registered_tools == {}
    
    def test_register_tool(self):
        """测试注册工具"""
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
        """测试注销工具"""
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
        """测试列出工具"""
        service = ToolService()
        
        # 注册一个工具
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
        """测试调用工具"""
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
