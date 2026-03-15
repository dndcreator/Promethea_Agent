from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from loguru import logger

from agentkit.mcp.mcp_manager import MCPManager, get_mcp_manager

from .events import EventEmitter
from .protocol import EventType
from .tools import ToolPolicy, ToolPolicyDecision, ToolRegistry


@dataclass
class ToolInvocationContext:
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolPolicyViolationError(RuntimeError):
    def __init__(self, message: str, decision: Optional[ToolPolicyDecision] = None):
        super().__init__(message)
        self.decision = decision


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
        tool_registry: Optional[ToolRegistry] = None,
        tool_policy: Optional[ToolPolicy] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.mcp_manager = mcp_manager or get_mcp_manager()
        self._registered_tools: Dict[str, Tool] = {}
        self.tool_registry = tool_registry or ToolRegistry()
        self.tool_policy = tool_policy or ToolPolicy()

    def register_tool(self, tool: Tool) -> None:
        if tool.tool_id in self._registered_tools:
            logger.warning(f"Tool already registered: {tool.tool_id}, will overwrite")
        self._registered_tools[tool.tool_id] = tool
        self.tool_registry.register_local_tool(tool)
        logger.info(f"Registered local tool: {tool.tool_id}")

    def unregister_tool(self, tool_id: str) -> None:
        if tool_id in self._registered_tools:
            del self._registered_tools[tool_id]
            self.tool_registry.unregister_spec(tool_id)
            logger.info(f"Unregistered local tool: {tool_id}")

    def _sync_registry_from_mcp(self) -> None:
        try:
            services_filtered = self.mcp_manager.get_available_services_filtered()
            self.tool_registry.register_mcp_services(services_filtered)
        except Exception as e:
            logger.debug(f"Tool registry MCP sync failed: {e}")

    async def list_tools(self) -> Dict[str, Any]:
        tools: List[Dict[str, Any]] = []
        self._sync_registry_from_mcp()

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

    async def get_tool_catalog(self) -> List[Dict[str, Any]]:
        self._sync_registry_from_mcp()
        raw = await self.list_tools()
        catalog: List[Dict[str, Any]] = []
        for service in raw.get("tools", []):
            service_name = service.get("service") or service.get("name")
            service_desc = service.get("description", "")
            tool_type = service.get("type", "unknown")
            actions = service.get("actions") or []
            if not actions:
                catalog.append(
                    {
                        "tool_type": tool_type,
                        "service_name": service_name,
                        "tool_name": service_name,
                        "description": service_desc,
                    }
                )
                continue
            for action in actions:
                catalog.append(
                    {
                        "tool_type": tool_type,
                        "service_name": service_name,
                        "tool_name": action.get("name") or service_name,
                        "description": action.get("description") or service_desc,
                    }
                )
        return catalog

    @staticmethod
    def _extract_run_context_fields(run_context: Optional[Any]) -> Dict[str, Any]:
        if run_context is None:
            return {}
        trace_id = getattr(run_context, "trace_id", None)
        request_id = getattr(run_context, "request_id", None)
        session_value = getattr(run_context, "session_id", None)
        user_value = getattr(run_context, "user_id", None)
        if session_value is None:
            session_state = getattr(run_context, "session_state", None)
            session_value = getattr(session_state, "session_id", None) if session_state is not None else None
            if user_value is None:
                user_value = getattr(session_state, "user_id", None) if session_state is not None else None
            if trace_id is None:
                trace_id = getattr(session_state, "trace_id", None) if session_state is not None else None
        fields: Dict[str, Any] = {}
        if trace_id:
            fields["trace_id"] = str(trace_id)
        if request_id:
            fields["request_id"] = str(request_id)
        if session_value:
            fields["session_id"] = str(session_value)
        if user_value:
            fields["user_id"] = str(user_value)
        return fields

    def _build_context_fields(
        self,
        *,
        ctx: Optional[ToolInvocationContext],
        run_context: Optional[Any],
    ) -> Dict[str, Any]:
        fields = self._extract_run_context_fields(run_context)
        if ctx:
            if ctx.session_id:
                fields["session_id"] = str(ctx.session_id)
            if ctx.user_id:
                fields["user_id"] = str(ctx.user_id)
            if ctx.source:
                fields["source"] = ctx.source
            metadata = ctx.metadata or {}
            if isinstance(metadata, dict):
                trace_id = metadata.get("trace_id")
                if trace_id and "trace_id" not in fields:
                    fields["trace_id"] = str(trace_id)
                request_meta = metadata.get("request_id")
                if request_meta and "request_id" not in fields:
                    fields["request_id"] = str(request_meta)
        return fields

    async def _assert_tool_namespace(
        self,
        *,
        run_context: Optional[Any],
        context_fields: Dict[str, Any],
        request_id: Optional[str],
        connection_id: Optional[str],
    ) -> None:
        if run_context is None:
            return
        context_user_id = str(context_fields.get("user_id") or "").strip()
        run_user_id = str(getattr(run_context, "user_id", "") or "").strip()
        if context_user_id and run_user_id and context_user_id != run_user_id:
            payload = {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "namespace": "tool",
                "owner_user_id": run_user_id,
                "requester_user_id": context_user_id,
                "reason": "cross_user_tool_access",
                "outcome": "blocked",
            }
            await self._emit_event(EventType.SECURITY_BOUNDARY_VIOLATION, payload)
            await self._emit_event(EventType.TOOL_CALL_ERROR, {**payload, "error": "forbidden tool access"})
            raise ToolPolicyViolationError("forbidden tool access")

    async def _authorize_tool_call(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        run_context: Optional[Any],
        context_fields: Dict[str, Any],
        request_id: Optional[str],
        connection_id: Optional[str],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        await self._assert_tool_namespace(
            run_context=run_context,
            context_fields=context_fields,
            request_id=request_id,
            connection_id=connection_id,
        )
        self._sync_registry_from_mcp()
        spec = self.tool_registry.resolve(tool_name=tool_name, params=params)

        # Keep backward compatibility for non-runtime callers that do not carry RunContext.
        if run_context is None:
            return {"spec": spec, "decision": None}

        decision = self.tool_policy.evaluate(spec=spec, run_context=run_context, user_config=user_config)
        if not decision.allowed:
            payload = {
                "request_id": request_id,
                "connection_id": connection_id,
                **context_fields,
                "tool_type": str(spec.source.value),
                "tool_name": spec.full_name,
                "error": decision.reason,
                "policy": decision.effective or {},
            }
            await self._emit_event(EventType.TOOL_CALL_ERROR, payload)
            raise ToolPolicyViolationError(decision.reason, decision=decision)

        return {"spec": spec, "decision": decision}

    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        ctx: Optional[ToolInvocationContext] = None,
        request_id: Optional[str] = None,
        connection_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        context_fields = self._build_context_fields(ctx=ctx, run_context=run_context)
        auth = await self._authorize_tool_call(
            tool_name=tool_name,
            params=params,
            run_context=run_context,
            context_fields=context_fields,
            request_id=request_id,
            connection_id=connection_id,
            user_config=user_config,
        )
        spec = auth["spec"]
        decision = auth["decision"]

        local_tool = self._registered_tools.get(tool_name)
        if local_tool is not None:
            await self._emit_event(
                EventType.TOOL_CALL_START,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
                    "tool_type": "local",
                    "tool_id": tool_name,
                    "args": params,
                    "tool_spec": spec.model_dump(mode="json"),
                    "policy": (decision.effective if decision else {}),
                },
            )
            try:
                result = await local_tool.invoke(params, ctx)
                await self._emit_event(
                    EventType.TOOL_CALL_RESULT,
                    {
                        "request_id": request_id,
                        "connection_id": connection_id,
                        **context_fields,
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
                        **context_fields,
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
                    **context_fields,
                    "tool_type": "agent",
                    "agent_name": agent_name,
                    "tool_spec": spec.model_dump(mode="json"),
                    "policy": (decision.effective if decision else {}),
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
                        **context_fields,
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
                        **context_fields,
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
                **context_fields,
                "tool_type": "mcp",
                "service_name": service_name,
                "tool_name": actual_tool_name,
                "args": args,
                "tool_spec": spec.model_dump(mode="json"),
                "policy": (decision.effective if decision else {}),
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
                    **context_fields,
                    "tool_type": "mcp",
                    "service_name": service_name,
                    "tool_name": actual_tool_name,
                    "result": result,
                },
            )
            return result
        except Exception as e:
            logger.error(f"MCP tool invocation failed [{service_name}.{actual_tool_name}]: {e}")
            await self._emit_event(
                EventType.TOOL_CALL_ERROR,
                {
                    "request_id": request_id,
                    "connection_id": connection_id,
                    **context_fields,
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
        mirror_map = {
            EventType.TOOL_CALL_START: EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_CALL_RESULT: EventType.TOOL_EXECUTION_FINISHED,
            EventType.TOOL_CALL_ERROR: EventType.TOOL_EXECUTION_FAILED,
        }
        try:
            await self.event_emitter.emit(event, payload)
            canonical_event = mirror_map.get(event)
            if canonical_event is not None:
                await self.event_emitter.emit(canonical_event, payload)
        except Exception as e:
            logger.error(f"Failed to emit tool event {event}: {e}")






