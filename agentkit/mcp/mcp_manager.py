import sys
import json
from loguru import logger
import asyncio
from typing import Any, Dict, List, Optional
from asyncio import AbstractEventLoop
from contextlib import AsyncExitStack
from aiohttp import ClientSession

try:
    from mcp import stdio_client, StdioServerParameters
    MCP_CLIENT_AVAILABLE = True
except ImportError:
    MCP_CLIENT_AVAILABLE = False
    logger.warning("MCP client package is not installed; MCP service connection is disabled")

from agentkit.mcp.mcpregistry import MCP_REGISTRY

class MCPManager:

    def __init__(self):

        self.services = {}
        self.tools_cache = {}
        self.exit_stack = AsyncExitStack()
        self.handoffs = {} 
        self.handoff_filters = {} 
        self.handoff_callbacks = {} 
        logger.info("MCPManager initialized")
    
    def register_handoff(self, 
    service_name: str, 
    tool_name: str, 
    tool_description: str, 
    input_schema: dict, 
    agent_name: str, 
    filters=None, 
    strict_schema=False):

        if service_name in self.services:
            logger.warning(f"Service {service_name} is already registered, skip")
            return
        
        self.services[service_name] = {
            "tool_name": tool_name,
            "tool_description": tool_description,
            "input_schema": input_schema,
            "agent_name": agent_name,
            "filter_fn": filters,
            "strict_schema": strict_schema
        }
        logger.info(f"Registered handoff service: {service_name}")

    async def _default_handoff_callback(ctx: Any, 
    input_json: Optional[str] = None) -> Any:
        return None
    
    async def handoff(self, 
    service_name: str, 
    task: dict, 
    input_history: Any = None, 
    pre_items: Any = None, 
    new_items: Any = None, 
    metadata: Optional[Dict[str, Any]] = None) -> str:

        try:
            task_json = json.dumps(task, ensure_ascii = False)
            logger.debug("Starting handoff: service={} task={}", service_name, task_json)

            if service_name not in self.services:
                raise ValueError(f"{service_name} is not registered")

            service = self.services[service_name]
            safe_info = {
                "name": service.get("name", ""),
                "description": service.get("description", ""),
                "agent_name": service.get("agent_name", ""),
                "strict_schema": service.get("strict_schema", False)
            }   
            safe_info_json = json.dumps(safe_info, ensure_ascii=False)
            logger.debug(f"Resolved service config: {safe_info_json}")     

            if service["strict_schema"]:
                required_fields = service["input_schema"].get("required", [])
                for field in required_fields:
                    if field not in task:
                        raise ValueError(f"Missing required field: {field}")
            if "messages" in task and service.get("filter_fn"):
                try:
                    task["messages"] = service["filter_fn"](task["messages"])
                except Exception as e:
                    logger.error(f"Message filter failed: {e}")     
            from agentkit.mcp.mcpregistry import MCP_REGISTRY
            agent_name = service["agent_name"]
            agent = MCP_REGISTRY.get(agent_name)
            if not agent:
                raise ValueError(f"{agent_name} is not registered")
            logger.info(f"Using registered Agent instance: {agent_name}")
            logger.info("Starting Agent handoff")
            result = await agent.handle_handoff(task)
            logger.debug("Agent handoff completed: service={} agent={}", service_name, agent_name)

            return result
    
        except Exception as e:
            error_report = f"Handoff execution failed: {str(e)}"
            logger.error(error_report)
            import traceback
            logger.exception(e)

            return json.dumps({
                "status": "failure",
                "report": error_report
            }, ensure_ascii = False)

    async def connect_service(self, service_name: str) -> Optional[ClientSession]:

        if service_name not in MCP_REGISTRY:
            logger.warning(f"MCP service not found: {service_name}")
            return None
        if service_name in self.services:
            return self.services[service_name]
        if not MCP_CLIENT_AVAILABLE:
            logger.warning(f"MCP client unavailable, cannot connect service {service_name}")
            return None
            
        service_config = MCP_REGISTRY[service_name]
        if not isinstance(service_config, dict):
            # Registry entries are often in-process service instances.
            return None
        if "script_path" not in service_config:
            return None
        command = "python" if service_config.get("type") == "python" else "node"
        try:
            logger.info(f"Connecting MCP service: {service_name}")
            server_parameters = StdioServerParameters(
                command = command,
                args = [service_config["script_path"]],
                env = None
            )
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_parameters)
            )
            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write)
            )
            await session.initialize()
            self.services[service_name] = session
            logger.info(f"MCP service {service_name} connected successfully")
            
            return session
        except Exception as e:
            logger.error(f"MCP service {service_name} connection failed: {str(e)}")
            logger.exception(e)

            return None
    
    async def get_service_tools_async(self, service_name: str) -> list:

        if service_name in self.tools_cache:
            return self.tools_cache[service_name]
        session = await self.connect_service(service_name)
        if not session:
            return []

        try:
            response = await session.list_tools()
            tools = response.tools
            self.tools_cache[service_name] = tools

            return tools
        except Exception as e:
            logger.error(f"Failed to get tools list for service {service_name}: {str(e)}")
            logger.exception(e)
            
            return []
    
    async def call_service_tool(self, service_name: str, tool_name: str, args: dict):

        session = await self.connect_service(service_name)
        if not session:
            return None
        try:
            logger.debug(f"Calling tool {service_name}.{tool_name} with args: {args}")
            result = await session.call_tool(tool_name, args)
            logger.debug(f"Tool call result for {service_name}.{tool_name}: {result}")

            return result
        except Exception as e:
            logger.error(f"Tool call {service_name}.{tool_name} failed: {str(e)}")
            logger.exception(e)

            return None
    
    async def unified_call(self, service_name: str, tool_name: str, args: dict):

        try:
            if service_name in self.services:
                return await self.handoff(service_name, args)
            
            if service_name in MCP_REGISTRY:
                agent = MCP_REGISTRY[service_name]
                if hasattr(agent, 'handle_handoff'):
                    return await agent.handle_handoff(args)
                elif hasattr(agent, tool_name):
                    method = getattr(agent, tool_name)
                    if callable(method):
                        filtered_args = {k: v for k, v in args.items() if k not in ['tool_name', 'service_name', 'agentType']}
                        
                        return await method(**filtered_args) if asyncio.iscoroutinefunction(method) else method(**filtered_args)
            return await self.call_service_tool(service_name, tool_name, args)
        except Exception as e:
            logger.error(f"Unified call failed for {service_name}.{tool_name}: {str(e)}")
            logger.exception(e)
            return f"Call failed: {str(e)}"

    def get_available_services(self) -> list:

        from agentkit.mcp.mcpregistry import get_all_services_info
        services_info = get_all_services_info()
        return [
            {
                "name": name,
                "description": info.get("description", ""),
                "label": info.get("label", name),
                "version": info.get("version", "1.0.0"),
                "available_tools": info.get("available_tools", []),
                "id": name
            }
            for name, info in services_info.items()
        ]
    
    def get_available_services_filtered(self) -> dict:

        from agentkit.mcp.mcpregistry import get_all_services_info, get_service_statistics
        mcp_services = []
        agent_services = []

        services_info = get_all_services_info()
        for name, info in services_info.items():
            service_info = {
                "name": name,
                "description": info.get("description", ""),
                "label": info.get("label", name),
                "version": info.get("version", "1.0.0"),
                "available_tools": info.get("available_tools", []),
                "id": name
            }
            mcp_services.append(service_info)

        for service_name, service_config in self.services.items():
            agent_service_info = {
                "name": service_name,
                "description": service_config.get("tool_description", ""),
                "tool_name": service_config.get("tool_name", ""),
                "id": service_name
            }
            agent_services.append(agent_service_info)
        return {
            "mcp_services": mcp_services,
            "agent_services": agent_services
        }
    
    def query_service_by_name(self, service_name: str) -> Optional[Dict[str, Any]]:

        from agentkit.mcp.mcpregistry import get_service_info
        
        return get_service_info(service_name)
    
    def query_services_by_capability(self, capability: str) -> List[Dict[str, Any]]:

        from agentkit.mcp.mcpregistry import query_services_by_capability, get_service_info
        matching_service_names = query_services_by_capability(capability)
        matching_services = []
        for service_name in matching_service_names:
            service_info = get_service_info(service_name)
            if service_info:
                matching_services.append({
                    "name": service_name,
                    "description": service_info.get("description", ""),
                    "label": service_info.get("label", service_name),
                    "version": service_info.get("version", "1.0.0"),
                    "available_tools": service_info.get("available_tools", []),
                })

        return matching_services
    
    def get_service_statistics(self) -> Dict[str, Any]:

        from agentkit.mcp.mcpregistry import get_service_statistics
        return get_service_statistics()
    
    def get_service_tools(self, service_name: str) -> List[Dict[str, Any]]:

        from agentkit.mcp.mcpregistry import get_available_tools
        return get_available_tools(service_name)
    
    def format_available_services(self) -> str:

        from agentkit.mcp.mcpregistry import get_all_services_info
        services_info = get_all_services_info()
        formatted_services = []
        for name, info in services_info.items():
            description = info.get("description", "")
            tools = info.get("available_tools", [])
            tool_names = [tool.get("name", "") for tool in tools]
            if description:
                formatted_services.append(f"- {name}: {description}")
                if tool_names:
                    formatted_services.append(f"  Available tools: {', '.join(tool_names)}")
            else:
                formatted_services.append(f"- {name}")
        return "\n".join(formatted_services)
    
    async def clean_services(self):

        logger.info("Cleaning MCP service runtime")
        try:
            await self.exit_stack.aclose()
            self.services.clear(); self.tools_cache.clear()
            logger.info("MCP services cleaned up")
        except Exception as e:
            logger.error("Failed to clean MCP services: {}", e)
            logger.exception(e)
    
    def get_mcp(self, name): return MCP_REGISTRY.get(name)

    def list_mcps(self): return list(MCP_REGISTRY.keys())

_MCP_MANAGER = None

def get_mcp_manager():

    global _MCP_MANAGER
    if not _MCP_MANAGER:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
