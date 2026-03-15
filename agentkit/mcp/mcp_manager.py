import asyncio
import json
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession
from loguru import logger
from pydantic import BaseModel, Field

from agentkit.mcp.mcpregistry import MCP_REGISTRY

try:
    from mcp import StdioServerParameters, stdio_client

    MCP_CLIENT_AVAILABLE = True
except ImportError:
    MCP_CLIENT_AVAILABLE = False
    logger.warning("MCP client package is not installed; MCP service connection is disabled")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MCPServiceHealth(BaseModel):
    service_name: str
    status: str = "offline"
    last_seen_at: Optional[str] = None
    last_sync_at: Optional[str] = None
    tool_count: int = 0
    last_error: Optional[str] = None
    source: str = "registry"
    user_visibility: str = "visible"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MCPToolDescriptor(BaseModel):
    tool_name: str
    service_name: str
    description: str = ""
    input_schema_summary: Dict[str, Any] = Field(default_factory=dict)
    status: str = "online"
    enabled: bool = True
    last_updated_at: Optional[str] = None
    source: str = "mcp_registry"
    user_visibility: str = "visible"


class MCPManager:
    def __init__(self):
        self.services: Dict[str, Any] = {}
        self.tools_cache: Dict[str, List[Any]] = {}
        self.health_cache: Dict[str, MCPServiceHealth] = {}
        self.exit_stack = AsyncExitStack()
        self.handoffs = {}
        self.handoff_filters = {}
        self.handoff_callbacks = {}
        logger.info("MCPManager initialized")

    def _ensure_health(self, service_name: str, *, source: str = "registry") -> MCPServiceHealth:
        health = self.health_cache.get(service_name)
        if health is not None:
            return health
        health = MCPServiceHealth(service_name=service_name, source=source)
        self.health_cache[service_name] = health
        return health

    def _mark_health(
        self,
        service_name: str,
        *,
        status: Optional[str] = None,
        source: Optional[str] = None,
        tool_count: Optional[int] = None,
        last_error: Optional[str] = None,
        touch_seen: bool = False,
        touch_sync: bool = False,
    ) -> MCPServiceHealth:
        health = self._ensure_health(service_name, source=source or "registry")
        if status:
            health.status = status
        if source:
            health.source = source
        if tool_count is not None:
            health.tool_count = int(tool_count)
        if last_error is not None:
            health.last_error = str(last_error) if last_error else None
        if touch_seen:
            health.last_seen_at = _utc_now_iso()
        if touch_sync:
            health.last_sync_at = _utc_now_iso()
        return health

    def _is_service_visible_for_user(self, service_name: str, user_id: Optional[str] = None) -> bool:
        from agentkit.mcp.mcpregistry import MANIFEST_CACHE

        manifest = MANIFEST_CACHE.get(service_name, {}) or {}
        visibility = manifest.get("visibility", {}) or {}
        blocked_users = set(visibility.get("blocked_users", []) or [])
        if user_id and user_id in blocked_users:
            return False
        allowed_users = visibility.get("users", []) or []
        if allowed_users:
            return bool(user_id and user_id in allowed_users)
        if "public" in visibility:
            return bool(visibility.get("public"))
        return True

    @staticmethod
    def _summarize_input_schema(raw_schema: Any) -> Dict[str, Any]:
        if not isinstance(raw_schema, dict):
            return {}
        props = raw_schema.get("properties", {})
        summary = {
            "type": raw_schema.get("type", "object"),
            "required": raw_schema.get("required", []) or [],
        }
        if isinstance(props, dict):
            summary["properties"] = sorted(list(props.keys()))
        return summary

    def register_handoff(
        self,
        service_name: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        agent_name: str,
        filters=None,
        strict_schema: bool = False,
    ):
        if service_name in self.services:
            logger.warning(f"Service {service_name} is already registered, skip")
            return

        self.services[service_name] = {
            "tool_name": tool_name,
            "tool_description": tool_description,
            "input_schema": input_schema,
            "agent_name": agent_name,
            "filter_fn": filters,
            "strict_schema": strict_schema,
        }
        logger.info(f"Registered handoff service: {service_name}")

    async def _default_handoff_callback(ctx: Any, input_json: Optional[str] = None) -> Any:
        return None

    async def handoff(
        self,
        service_name: str,
        task: dict,
        input_history: Any = None,
        pre_items: Any = None,
        new_items: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        try:
            task_json = json.dumps(task, ensure_ascii=False)
            logger.debug("Starting handoff: service={} task={}", service_name, task_json)

            if service_name not in self.services:
                raise ValueError(f"{service_name} is not registered")

            service = self.services[service_name]
            safe_info = {
                "name": service.get("name", ""),
                "description": service.get("description", ""),
                "agent_name": service.get("agent_name", ""),
                "strict_schema": service.get("strict_schema", False),
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
            logger.exception(e)

            return json.dumps({"status": "failure", "report": error_report}, ensure_ascii=False)

    async def connect_service(self, service_name: str) -> Optional[ClientSession]:
        if service_name not in MCP_REGISTRY:
            logger.warning(f"MCP service not found: {service_name}")
            self._mark_health(
                service_name,
                status="offline",
                source="registry",
                last_error="service not registered",
            )
            return None

        if service_name in self.services:
            self._mark_health(service_name, status="online", touch_seen=True, last_error=None)
            current = self.services[service_name]
            return current if isinstance(current, ClientSession) else None

        if not MCP_CLIENT_AVAILABLE:
            logger.warning(f"MCP client unavailable, cannot connect service {service_name}")
            self._mark_health(
                service_name,
                status="degraded",
                source="runtime",
                last_error="MCP client package unavailable",
                touch_seen=True,
            )
            return None

        service_config = MCP_REGISTRY[service_name]
        if not isinstance(service_config, dict):
            # Registry entries are often in-process service instances.
            self._mark_health(
                service_name,
                status="online",
                source="inprocess",
                touch_seen=True,
                last_error=None,
            )
            return None

        if "script_path" not in service_config:
            self._mark_health(
                service_name,
                status="degraded",
                source="runtime",
                touch_seen=True,
                last_error="missing script_path in service config",
            )
            return None

        command = "python" if service_config.get("type") == "python" else "node"
        try:
            logger.info(f"Connecting MCP service: {service_name}")
            server_parameters = StdioServerParameters(command=command, args=[service_config["script_path"]], env=None)
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_parameters))
            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
            await session.initialize()
            self.services[service_name] = session
            logger.info(f"MCP service {service_name} connected successfully")
            self._mark_health(
                service_name,
                status="online",
                source="runtime",
                touch_seen=True,
                last_error=None,
            )
            return session
        except Exception as e:
            logger.error(f"MCP service {service_name} connection failed: {str(e)}")
            logger.exception(e)
            self._mark_health(
                service_name,
                status="degraded",
                source="runtime",
                touch_seen=True,
                last_error=str(e),
            )
            return None

    async def get_service_tools_async(self, service_name: str) -> list:
        if service_name in self.tools_cache:
            cached = self.tools_cache[service_name]
            self._mark_health(
                service_name,
                status="online",
                tool_count=len(cached or []),
                touch_seen=True,
                touch_sync=True,
            )
            return cached

        session = await self.connect_service(service_name)
        if not session:
            try:
                # Fallback for in-process registry-only services.
                from agentkit.mcp.mcpregistry import get_available_tools

                tools = get_available_tools(service_name)
                self.tools_cache[service_name] = tools
                current_health = self._ensure_health(service_name)
                fallback_error = current_health.last_error or "service has no discoverable tools"
                self._mark_health(
                    service_name,
                    status="online" if tools else "degraded",
                    tool_count=len(tools),
                    touch_seen=True,
                    touch_sync=True,
                    last_error=None if tools else fallback_error,
                )
                return tools
            except Exception:
                return []

        try:
            response = await session.list_tools()
            tools = response.tools
            self.tools_cache[service_name] = tools
            self._mark_health(
                service_name,
                status="online",
                tool_count=len(tools or []),
                touch_seen=True,
                touch_sync=True,
                last_error=None,
            )
            return tools
        except Exception as e:
            logger.error(f"Failed to get tools list for service {service_name}: {str(e)}")
            logger.exception(e)
            self._mark_health(
                service_name,
                status="degraded",
                touch_seen=True,
                touch_sync=True,
                last_error=str(e),
            )
            return []

    async def call_service_tool(self, service_name: str, tool_name: str, args: dict):
        session = await self.connect_service(service_name)
        if not session:
            return None

        try:
            logger.debug(f"Calling tool {service_name}.{tool_name} with args: {args}")
            result = await session.call_tool(tool_name, args)
            logger.debug(f"Tool call result for {service_name}.{tool_name}: {result}")
            self._mark_health(service_name, status="online", touch_seen=True, last_error=None)
            return result
        except Exception as e:
            logger.error(f"Tool call {service_name}.{tool_name} failed: {str(e)}")
            logger.exception(e)
            self._mark_health(
                service_name,
                status="degraded",
                touch_seen=True,
                last_error=str(e),
            )
            return None

    async def unified_call(self, service_name: str, tool_name: str, args: dict):
        try:
            if service_name in self.services:
                return await self.handoff(service_name, args)

            if service_name in MCP_REGISTRY:
                agent = MCP_REGISTRY[service_name]
                if hasattr(agent, "handle_handoff"):
                    return await agent.handle_handoff(args)
                if hasattr(agent, tool_name):
                    method = getattr(agent, tool_name)
                    if callable(method):
                        filtered_args = {
                            k: v
                            for k, v in args.items()
                            if k not in ["tool_name", "service_name", "agentType"]
                        }
                        out = (
                            await method(**filtered_args)
                            if asyncio.iscoroutinefunction(method)
                            else method(**filtered_args)
                        )
                        self._mark_health(service_name, status="online", touch_seen=True, last_error=None)
                        return out

            return await self.call_service_tool(service_name, tool_name, args)
        except Exception as e:
            logger.error(f"Unified call failed for {service_name}.{tool_name}: {str(e)}")
            logger.exception(e)
            self._mark_health(
                service_name,
                status="degraded",
                touch_seen=True,
                last_error=str(e),
            )
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
                "id": name,
                "health": self.get_service_health(name),
            }
            for name, info in services_info.items()
        ]

    def list_service_health(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_all_services_info

        services_info = get_all_services_info()
        rows: List[Dict[str, Any]] = []
        for service_name in services_info.keys():
            visible = self._is_service_visible_for_user(service_name, user_id=user_id)
            health = self._ensure_health(service_name)
            health.user_visibility = "visible" if visible else "hidden"
            if health.last_seen_at is None:
                health.status = "offline"
            rows.append(health.model_dump())
        return rows

    def get_service_health(self, service_name: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        visible = self._is_service_visible_for_user(service_name, user_id=user_id)
        health = self._ensure_health(service_name)
        health.user_visibility = "visible" if visible else "hidden"
        return health.model_dump()

    async def list_tool_descriptors(
        self,
        *,
        service_name: Optional[str] = None,
        user_id: Optional[str] = None,
        include_hidden: bool = False,
    ) -> List[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_all_services_info, get_available_tools

        services_info = get_all_services_info()
        selected = [service_name] if service_name else list(services_info.keys())
        rows: List[Dict[str, Any]] = []

        for svc in selected:
            if svc not in services_info:
                continue

            tools = await self.get_service_tools_async(svc)
            if not tools:
                tools = get_available_tools(svc)

            is_visible = self._is_service_visible_for_user(svc, user_id=user_id)
            visibility_label = "visible" if is_visible else "hidden"
            health = self._ensure_health(svc)
            status = health.status or "offline"
            source = health.source or "mcp_registry"
            last_updated = health.last_sync_at or health.last_seen_at or _utc_now_iso()

            normalized_tools: List[Dict[str, Any]] = []
            for raw in tools:
                if isinstance(raw, dict):
                    normalized_tools.append(raw)
                else:
                    normalized_tools.append(
                        {
                            "name": getattr(raw, "name", ""),
                            "description": getattr(raw, "description", ""),
                            "input_schema": getattr(raw, "inputSchema", {})
                            or getattr(raw, "input_schema", {}),
                        }
                    )

            for tool in normalized_tools:
                descriptor = MCPToolDescriptor(
                    tool_name=str(tool.get("name") or ""),
                    service_name=svc,
                    description=str(tool.get("description") or ""),
                    input_schema_summary=self._summarize_input_schema(tool.get("input_schema") or {}),
                    status=status,
                    enabled=bool(tool.get("enabled", True)),
                    last_updated_at=last_updated,
                    source=source,
                    user_visibility=visibility_label,
                )
                if include_hidden or descriptor.user_visibility == "visible":
                    rows.append(descriptor.model_dump())

        return rows

    async def list_visible_tools_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        return await self.list_tool_descriptors(user_id=user_id, include_hidden=False)

    def get_available_services_filtered(self) -> dict:
        from agentkit.mcp.mcpregistry import get_all_services_info

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
                "id": name,
            }
            mcp_services.append(service_info)

        for service_name, service_config in self.services.items():
            if not isinstance(service_config, dict):
                continue
            agent_service_info = {
                "name": service_name,
                "description": service_config.get("tool_description", ""),
                "tool_name": service_config.get("tool_name", ""),
                "id": service_name,
            }
            agent_services.append(agent_service_info)

        return {
            "mcp_services": mcp_services,
            "agent_services": agent_services,
        }

    def query_service_by_name(self, service_name: str) -> Optional[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_service_info

        return get_service_info(service_name)

    def query_services_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_service_info, query_services_by_capability

        matching_service_names = query_services_by_capability(capability)
        matching_services = []
        for service_name in matching_service_names:
            service_info = get_service_info(service_name)
            if service_info:
                matching_services.append(
                    {
                        "name": service_name,
                        "description": service_info.get("description", ""),
                        "label": service_info.get("label", service_name),
                        "version": service_info.get("version", "1.0.0"),
                        "available_tools": service_info.get("available_tools", []),
                    }
                )

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
            self.services.clear()
            self.tools_cache.clear()
            logger.info("MCP services cleaned up")
        except Exception as e:
            logger.error("Failed to clean MCP services: {}", e)
            logger.exception(e)

    def get_mcp(self, name):
        return MCP_REGISTRY.get(name)

    def list_mcps(self):
        return list(MCP_REGISTRY.keys())


_MCP_MANAGER = None


def get_mcp_manager():
    global _MCP_MANAGER
    if not _MCP_MANAGER:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
