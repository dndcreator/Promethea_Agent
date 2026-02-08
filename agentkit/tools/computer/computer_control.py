"""
电脑控制 MCP 服务适配器
将底层 computer 模块的能力暴露给 MCP 框架
"""
from loguru import logger
import asyncio
import base64
from typing import Dict, Any, Optional
from computer.base import ComputerCapability
from gateway_integration import GatewayIntegration


class ComputerControlService:
    """电脑控制服务 (MCP Wrapper)"""
    
    def __init__(self):
        self.name = "computer_control"
        self.gateway = None

    async def execute_action(self, capability: str, action: str, params: Dict[str, Any] = None) -> str:
        """执行电脑操作"""
        try:
            # 动态导入以避免循环依赖
            from gateway_integration import get_gateway_integration
            
            # 获取全局单例
            gateway = get_gateway_integration()
            if not gateway:
                return "❌ 网关系统未初始化，无法执行电脑操作"

            # 构造参数
            if params is None:
                params = {}
                
            logger.info(f"执行电脑操作: {capability}.{action} params={params}")
            
            # 使用网关集成的统一方法执行，复用全局 Controller
            result = await gateway.execute_computer_action(capability, action, params)
            
            if result.success:
                output = f"✅ 操作成功\n"
                if result.result:
                    output += f"结果: {result.result}\n"
                if result.screenshot:
                    output += f"[包含截图数据: {len(result.screenshot)} bytes]\n"
                return output
            else:
                return f"❌ 操作失败: {result.error}"

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"❌ 系统错误: {str(e)}"

    async def browser_action(self, action: str, url: str = "", selector: str = "", text: str = "") -> str:
        """浏览器操作"""
        params = {}
        if url: params["url"] = url
        if selector: params["selector"] = selector
        if text: params["text"] = text
        
        return await self.execute_action(ComputerCapability.BROWSER, action, params)

    async def screen_action(self, action: str, x: int = 0, y: int = 0, text: str = "", key: str = "") -> str:
        """屏幕/键鼠操作"""
        params = {}
        if x or y: 
            params["x"] = x
            params["y"] = y
        if text: params["text"] = text
        if key: params["key"] = key
        
        # 根据 action 映射到正确的 capability
        cap = ComputerCapability.SCREEN
        if action in ["move", "click", "scroll"]: cap = ComputerCapability.MOUSE
        if action in ["type", "press"]: cap = ComputerCapability.KEYBOARD
        if action == "screenshot": cap = ComputerCapability.SCREENSHOT
        
        return await self.execute_action(cap, action, params)

    async def fs_action(self, action: str, path: str, content: str = "") -> str:
        """文件系统操作"""
        params = {"path": path}
        if content: params["content"] = content
        return await self.execute_action(ComputerCapability.FILESYSTEM, action, params)
