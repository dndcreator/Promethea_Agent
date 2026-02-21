"""
Computer control MCP service adapter.

Expose low-level capabilities of the `computer` module to the MCP framework.
"""
from loguru import logger
import asyncio
import base64
from typing import Dict, Any, Optional
from computer.base import ComputerCapability
from gateway_integration import GatewayIntegration


class ComputerControlService:
    """Computer control service (MCP wrapper)."""
    
    def __init__(self):
        self.name = "computer_control"
        self.gateway = None

    async def execute_action(self, capability: str, action: str, params: Dict[str, Any] = None) -> str:
        """Execute a computer control action via the gateway."""
        try:
            from gateway_integration import get_gateway_integration
            
            gateway = get_gateway_integration()
            if not gateway:
                return "Error: gateway system is not initialized, cannot run computer actions"

            if params is None:
                params = {}
            
            logger.info(f"Executing computer action: {capability}.{action} params={params}")
            
            result = await gateway.execute_computer_action(capability, action, params)
            
            if result.success:
                output = "SUCCESS: operation completed\n"
                if result.result:
                    output += f"Result: {result.result}\n"
                if result.screenshot:
                    output += f"[Including screenshot data: {len(result.screenshot)} bytes]\n"
                return output
            else:
                return f"ERROR: operation failed: {result.error}"

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"ERROR: system exception: {str(e)}"

    async def browser_action(self, action: str, url: str = "", selector: str = "", text: str = "") -> str:
        """Browser operations."""
        params = {}
        if url: params["url"] = url
        if selector: params["selector"] = selector
        if text: params["text"] = text
        
        return await self.execute_action(ComputerCapability.BROWSER, action, params)

    async def screen_action(self, action: str, x: int = 0, y: int = 0, text: str = "", key: str = "") -> str:
        """Screen, mouse and keyboard operations."""
        params = {}
        if x or y: 
            params["x"] = x
            params["y"] = y
        if text: params["text"] = text
        if key: params["key"] = key
        
        cap = ComputerCapability.SCREEN
        if action in ["move", "click", "scroll"]: cap = ComputerCapability.MOUSE
        if action in ["type", "press"]: cap = ComputerCapability.KEYBOARD
        if action == "screenshot": cap = ComputerCapability.SCREENSHOT
        
        return await self.execute_action(cap, action, params)

    async def fs_action(self, action: str, path: str, content: str = "") -> str:
        """File system operations."""
        params = {"path": path}
        if content: params["content"] = content
        return await self.execute_action(ComputerCapability.FILESYSTEM, action, params)
