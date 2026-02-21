from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from loguru import logger

from agentkit.mcp.mcp_manager import MCPManager, get_mcp_manager

from .events import EventEmitter
from .protocol import EventType


@dataclass
class ToolInvocationContext:
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    tool_id: str
    name: str
    description: str

    async def invoke(
        self,
        args: Dict[str, Any],
        ctx: Optional[ToolInvocationContext] = None,
    ) -> Any:  # pragma: no cover - protocol interface
        ...


class ToolService:
    """Unified tool invocation entry for local tools + MCP tools."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        mcp_manager: Optional[MCPManager] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.mcp_manager = mcp_manager or get_mcp_manager()
        self._registered_tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        if tool.tool_id in self._registered_tools:
            logger.warning(f"Tool already registered: {tool.tool_id}, will overwrite")
        self._registered_tools[tool.tool_id] = tool
        logger.info(f"Registered local tool: {tool.tool_id}")

    def unregister_tool(self, tool_id: str) -> None:
        if tool_id in self._registered_tools:
            del self._registered_tools[tool_id]
            logger.info(f"Unregistered local tool: {tool_id}")

    async def list_tools(self) -> Dict[str, Any]:
        tools: List[Dict[str, Any]] = []

        try:
            services_filtered = self.mcp_manager.get_available_services_filtered()
            mcp_services = services_filtered.get("mcp_services", [])
            agent_services = services_filtered.get("agent_services", [])

            for svc in mcp_services:
                tools.append(
                    {
                        "service": svc.get("name"),
                        "name": svc.get("label", svc.get("name")),
                        "description": svc.get("description", ""),
                        "actions": svc.get("available_tools", []),
                        "type": "mcp",
                    }
                )

            for svc in agent_services:
                tools.append(
                    {
                        "service": svc.get("name"),
                        "name": svc.get("name"),
                        "description": svc.get("description", ""),
                        "actions": [
                            {
                                "name": svc.get("tool_name", "handoff"),
                                "description": svc.get("description", ""),
                            }
                        ],
                        "type": "agent",
                    }
                )
        except Exception as e:
            logger.error(f"Failed to list MCP/agent tools: {e}")

        for tool_id, tool in self._registered_tools.items():
            tools.append(
                {
                    "service": tool_id,
                    "name": getattr(tool, "name", tool_id),
                    "description": getattr(tool, "description", ""),
                    "actions": [],
                    "type": "local",
                }
            )

        return {"tools": tools, "total": len(tools)}

    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        ctx: Optional[ToolInvocationContext] = None,
        request_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> Any:
        local_tool = self._registered_tools.get(tool_name)
        if local_tool is not None:
            await self._emit_event(
                EventType.TOOL_CALL_START,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    "tool_type": "local",
                    "tool_id": tool_name,
                    "args": params,
                },
            )
            try:
                result = await local_tool.invoke(params, ctx)
                await self._emit_event(
                    EventType.TOOL_CALL_RESULT,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        "tool_type": "local",
                        "tool_id": tool_name,
                        "result": result,
                    },
                )
                return result
            except Exception as e:
                logger.error(f"Local tool invocation failed [{tool_name}]: {e}")
                await self._emit_event(
                    EventType.TOOL_CALL_ERROR,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        "tool_type": "local",
                        "tool_id": tool_name,
                        "error": str(e),
                    },
                )
                raise

        agent_type = str(params.get("agentType", "mcp")).lower()
        if agent_type == "agent":
            agent_name = params.get("agent_name")
            prompt = params.get("prompt")
            if not agent_name or not prompt:
                raise ValueError("agent tool call requires agent_name and prompt")
            await self._emit_event(
                EventType.TOOL_CALL_START,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    "tool_type": "agent",
                    "agent_name": agent_name,
                },
            )
            try:
                from agentkit.mcp.agent_manager import get_agent_manager

                agent_manager = get_agent_manager()
                result = await agent_manager.call_agent(
                    str(agent_name),
                    str(prompt),
                    getattr(ctx, "session_id", None) if ctx else None,
                )
                await self._emit_event(
                    EventType.TOOL_CALL_RESULT,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        "tool_type": "agent",
                        "agent_name": agent_name,
                        "result": result,
                    },
                )
                return result
            except Exception as e:
                await self._emit_event(
                    EventType.TOOL_CALL_ERROR,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        "tool_type": "agent",
                        "agent_name": agent_name,
                        "error": str(e),
                    },
                )
                raise

        service_name = params.get("service_name") or tool_name
        actual_tool_name = params.get("tool_name") or params.get("command") or tool_name
        args = {
            k: v
            for k, v in params.items()
            if k not in {"service_name", "tool_name", "agentType"}
        }

        await self._emit_event(
            EventType.TOOL_CALL_START,
            {
                "request_id": request_id,
                "connection_id": connection_id,
                "tool_type": "mcp",
                "service_name": service_name,
                "tool_name": actual_tool_name,
                "args": args,
                "session_id": getattr(ctx, "session_id", None) if ctx else None,
                "user_id": getattr(ctx, "user_id", None) if ctx else None,
                "source": getattr(ctx, "source", None) if ctx else None,
            },
        )

        try:
            result = await self.mcp_manager.unified_call(
                service_name=service_name,
                tool_name=actual_tool_name,
                args=args,
            )
            await self._emit_event(
                EventType.TOOL_CALL_RESULT,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "tool_name": actual_tool_name,
                    "result": result,
                },
            )
            return result
        except Exception as e:
            logger.error(
                f"MCP tool invocation failed [{service_name}.{actual_tool_name}]: {e}"
            )
            await self._emit_event(
                EventType.TOOL_CALL_ERROR,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "tool_name": actual_tool_name,
                    "error": str(e),
                },
            )
            raise

    async def _emit_event(self, event: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        try:
            await self.event_emitter.emit(event, payload)
        except Exception as e:
            logger.error(f"Failed to emit tool event {event}: {e}")
