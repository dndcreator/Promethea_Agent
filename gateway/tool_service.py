from __future__ import annotations

"""
工具系统服务层

目标：
- 把 Gateway 中的“工具/技能”能力抽象成一个独立的 ToolService
- 复用现有 MCPManager / MCP_REGISTRY 逻辑，不重新造轮子
- 在网关事件总线上发出工具调用的生命周期事件（start / result / error）
- 为后续本地工具、非 MCP 工具预留统一的接口和注册点
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Callable, List

from loguru import logger

from .events import EventEmitter
from .protocol import EventType
from agentkit.mcp.mcp_manager import MCPManager, get_mcp_manager


@dataclass
class ToolInvocationContext:
    """
    工具调用上下文（可扩展）
    - session_id: 来自会话/对话核心
    - user_id: 触发该调用的用户标识
    - source: 调用来源（gateway / http-api / channel 等）
    - metadata: 其他上下文信息（如 channel, message_id 等）
    """

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    """
    抽象工具接口

    说明：
    - 这里定义的是“一级能力”的接口，和记忆/对话处于同一层级
    - 具体 MCP 工具、本地 Python 工具、Agent handoff 等都可以实现该接口
    """

    tool_id: str
    name: str
    description: str

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:  # pragma: no cover - 协议接口
        ...


class ToolService:
    """
    工具服务（对 Gateway 暴露的统一入口）

    - 提供工具注册/查询/调用接口
    - 通过 MCPManager 复用现有 MCP / Agent handoff 能力
    - 在 EventEmitter 上发出 TOOL_CALL_* 事件，方便多 Agent 调度/监控
    """

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        mcp_manager: Optional[MCPManager] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.mcp_manager = mcp_manager or get_mcp_manager()

        # 本地注册的工具（非 MCP），例如内置 Python 工具、系统运维工具等
        self._registered_tools: Dict[str, Tool] = {}

    # ===== 工具注册 API（为未来扩展预留） =====

    def register_tool(self, tool: Tool) -> None:
        """
        注册一个本地工具

        tool.tool_id 建议采用 `namespace.name` 形式，避免与 MCP service 冲突。
        """
        if tool.tool_id in self._registered_tools:
            logger.warning(f"Tool already registered: {tool.tool_id}, will overwrite")
        self._registered_tools[tool.tool_id] = tool
        logger.info(f"Registered local tool: {tool.tool_id}")

    def unregister_tool(self, tool_id: str) -> None:
        """注销本地工具"""
        if tool_id in self._registered_tools:
            del self._registered_tools[tool_id]
            logger.info(f"Unregistered local tool: {tool_id}")

    # ===== 查询 API =====

    async def list_tools(self) -> Dict[str, Any]:
        """
        列出所有可用“工具入口”

        兼容现有 gateway `tools.list` 协议：
        {
            "tools": [
                {
                    "service": "...",       # MCP 服务或本地工具命名空间
                    "name": "...",          # 展示名称
                    "description": "...",
                    "actions": [...]        # 可用具体 command / 子工具
                },
                ...
            ],
            "total": N
        }
        """
        tools: List[Dict[str, Any]] = []

        # 1) MCP / Agent handoff 服务（复用 MCPManager 的封装）
        try:
            services_filtered = self.mcp_manager.get_available_services_filtered()
            mcp_services = services_filtered.get("mcp_services", [])
            agent_services = services_filtered.get("agent_services", [])

            # MCP services
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

            # Agent handoff 视为一种“工具服务”
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
        except Exception as e:  # pragma: no cover - 容错分支
            logger.error(f"Failed to list MCP/agent tools: {e}")

        # 2) 本地注册工具（统一挂在 type=local）
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

    # ===== 调用 API =====

    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        ctx: Optional[ToolInvocationContext] = None,
        request_id: Optional[str] = None,
        connection_id: Optional[str] = None,
    ) -> Any:
        """
        调用一个工具

        约定（兼容现有用法）：
        - gateway 侧 `tool_name` 通常是 MCP service 名，params 里可以带：
          - service_name: 具体服务名（可选，默认等于 tool_name）
          - tool_name:    具体 command / 子工具名（可选，默认等于 tool_name）
          - 其他字段为业务参数
        - 对于本地 Tool：tool_name = tool.tool_id
        """

        # 先尝试本地注册工具（为后续扩展预留）
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
            except Exception as e:  # pragma: no cover - 容错分支
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

        # MCP / Agent 工具调用
        service_name = params.get("service_name") or tool_name
        actual_tool_name = params.get("tool_name") or params.get("command") or tool_name

        # 过滤出真正的参数，避免把 service_name / tool_name / agentType 反复传入
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

    # ===== 内部工具 =====

    async def _emit_event(self, event: EventType, payload: Dict[str, Any]) -> None:
        """在事件总线上发出工具相关事件（如果总线可用的话）"""
        if not self.event_emitter:
            return
        try:
            await self.event_emitter.emit(event, payload)
        except Exception as e:  # pragma: no cover - 防御性代码
            logger.error(f"Failed to emit tool event {event}: {e}")

