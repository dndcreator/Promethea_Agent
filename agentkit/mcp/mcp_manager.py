import os
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
    status: str = "unknown"
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
        self.mcp_sessions: Dict[str, ClientSession] = {}
        self.tools_cache: Dict[str, List[Any]] = {}
        self._catalog_refresh_attempted = False
        self.health_cache: Dict[str, MCPServiceHealth] = {}
        self.exit_stack = AsyncExitStack()
        logger.info("MCPManager initialized")

    def _ensure_health(self, service_name: str, *, source: str = "registry") -> MCPServiceHealth:
        health = self.health_cache.get(service_name)
        if health is not None:
            return health
        status = "unknown"
        health = MCPServiceHealth(service_name=service_name, source=source, status=status)
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

        if service_name in self.mcp_sessions:
            self._mark_health(service_name, status="online", touch_seen=True, last_error=None)
            return self.mcp_sessions[service_name]

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
        command = str(service_config.get("command") or "").strip()
        args = service_config.get("args") or []
        if not command or not isinstance(args, list):
            self._mark_health(
                service_name,
                status="degraded",
                source="runtime",
                touch_seen=True,
                last_error="invalid external MCP stdio config",
            )
            return None
        configured_env = service_config.get("env") or {}
        resolved_env = dict(os.environ)
        for key, value in configured_env.items():
            text = str(value)
            if text.startswith("${") and text.endswith("}"):
                text = os.environ.get(text[2:-1], "")
            resolved_env[str(key)] = text
        try:
            logger.info(f"Connecting MCP service: {service_name}")
            server_parameters = StdioServerParameters(
                command=command,
                args=[str(item) for item in args],
                env=resolved_env,
                cwd=service_config.get("cwd"),
            )
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_parameters))
            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
            await session.initialize()
            self.mcp_sessions[service_name] = session
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

    async def refresh_registered_tools(self) -> None:
        """Populate the cached catalog from every configured external provider."""
        if self._catalog_refresh_attempted:
            return
        self._catalog_refresh_attempted = True
        for service_name in list(MCP_REGISTRY):
            await self.get_service_tools_async(service_name)

    def invalidate_tool_catalog(self) -> None:
        self.tools_cache.clear()
        self._catalog_refresh_attempted = False

    @staticmethod
    def _catalog_tool(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return {
                "name": str(raw.get("name") or raw.get("tool_name") or ""),
                "description": str(raw.get("description") or ""),
                "input_schema": raw.get("input_schema") or raw.get("inputSchema") or {},
                "side_effect_level": raw.get("side_effect_level"),
                "side_effect_selector": raw.get("side_effect_selector") or {},
                "requires_capability": raw.get("requires_capability"),
                "requires_config": raw.get("requires_config"),
                "owner_user_id": raw.get("owner_user_id"),
            }
        return {
            "name": str(getattr(raw, "name", "") or ""),
            "description": str(getattr(raw, "description", "") or ""),
            "input_schema": getattr(raw, "inputSchema", {}) or getattr(raw, "input_schema", {}) or {},
        }

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

    def list_service_health(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_all_services_info

        services_info = get_all_services_info()
        rows: List[Dict[str, Any]] = []
        for service_name in services_info.keys():
            visible = self._is_service_visible_for_user(service_name, user_id=user_id)
            health = self._ensure_health(service_name)
            health.user_visibility = "visible" if visible else "hidden"
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
        services_info = get_all_services_info()
        for name, info in services_info.items():
            cached_tools = [
                self._catalog_tool(item)
                for item in (self.tools_cache.get(name) or [])
            ]
            service_info = {
                "name": name,
                "description": info.get("description", ""),
                "label": info.get("label", name),
                "version": info.get("version", "1.0.0"),
                "available_tools": cached_tools or info.get("available_tools", []),
                "id": name,
            }
            mcp_services.append(service_info)

        return {"mcp_services": mcp_services}

    def query_service_by_name(self, service_name: str) -> Optional[Dict[str, Any]]:
        from agentkit.mcp.mcpregistry import get_service_info

        return get_service_info(service_name)

    async def clean_services(self):
        logger.info("Cleaning MCP service runtime")
        try:
            await self.exit_stack.aclose()
            self.mcp_sessions.clear()
            self.invalidate_tool_catalog()
            self.exit_stack = AsyncExitStack()
            logger.info("MCP services cleaned up")
        except Exception as e:
            logger.error("Failed to clean MCP services: {}", e)
            logger.exception(e)

_MCP_MANAGER = None


def get_mcp_manager():
    global _MCP_MANAGER
    if not _MCP_MANAGER:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
