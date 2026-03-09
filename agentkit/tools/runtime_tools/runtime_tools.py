from __future__ import annotations

from typing import Any, Dict, List

from agentkit.mcp.agent_manager import get_agent_manager
from core.plugins.runtime import get_active_plugin_registry
from gateway.http.message_manager import message_manager
from gateway.tool_service import ToolService
from gateway_integration import get_gateway_integration


class RuntimeToolsService:
    """Runtime and gateway-level operational tools."""

    def __init__(self):
        self.name = "runtime_tools"

    async def gateway_action(self, action: str = "status") -> Dict[str, Any]:
        integration = get_gateway_integration()
        if not integration:
            return {"ok": False, "status": "disabled", "message": "Gateway not initialized"}

        server = integration.get_gateway_server()
        if action == "status":
            return {
                "ok": True,
                "gateway_running": bool(server and server.is_running),
                "connections": server.connection_manager.get_active_count() if server else 0,
                "services": server.get_services_health() if server else {},
            }

        if action == "routes":
            methods = sorted([str(k.value) for k in server._handlers.keys()]) if server else []  # noqa: SLF001
            return {"ok": True, "routes": methods, "total": len(methods)}

        if action == "tools":
            tool_service = server.tool_service if server else None
            if not tool_service and server:
                tool_service = ToolService(server.event_emitter)
                server.tool_service = tool_service
            catalog = await tool_service.get_tool_catalog() if tool_service else []
            return {"ok": True, "tools": catalog, "total": len(catalog)}

        raise ValueError(f"unsupported gateway action: {action}")

    async def sessions_action(
        self,
        action: str = "list",
        session_id: str = "",
        user_id: str = "default_user",
        agent_type: str = "",
    ) -> Dict[str, Any]:
        uid = str(user_id or "default_user")

        if action == "list":
            sessions = message_manager.get_all_sessions_info(user_id=uid)
            rows = sorted(sessions.values(), key=lambda x: float(x.get("last_activity", 0)), reverse=True)
            return {"ok": True, "total": len(rows), "sessions": rows}

        if not session_id:
            raise ValueError("session_id is required")

        if action == "detail":
            session = message_manager.get_session(session_id, user_id=uid)
            if not session:
                return {"ok": False, "error": "session not found", "session_id": session_id}
            return {"ok": True, "session_id": session_id, "session": session}

        if action == "delete":
            deleted = message_manager.delete_session(session_id, user_id=uid)
            return {"ok": bool(deleted), "session_id": session_id, "deleted": bool(deleted)}

        if action == "set_agent_type":
            if not agent_type:
                raise ValueError("agent_type is required")
            updated = message_manager.set_agent_type(session_id, agent_type=agent_type, user_id=uid)
            return {"ok": bool(updated), "session_id": session_id, "agent_type": agent_type}

        raise ValueError(f"unsupported sessions action: {action}")

    async def agents_action(self, action: str = "list", agent_name: str = "") -> Dict[str, Any]:
        manager = get_agent_manager()

        if action == "list":
            agents = manager.get_available_agents()
            return {"ok": True, "total": len(agents), "agents": agents}

        if action == "get":
            if not agent_name:
                raise ValueError("agent_name is required")
            info = manager.get_agent_info(agent_name)
            if not info:
                return {"ok": False, "error": "agent not found", "agent_name": agent_name}
            return {"ok": True, "agent": info}

        raise ValueError(f"unsupported agents action: {action}")

    async def memory_action(
        self,
        action: str = "search",
        query: str = "",
        session_id: str = "",
        user_id: str = "default_user",
    ) -> Dict[str, Any]:
        integration = get_gateway_integration()
        if not integration or not integration.gateway_server or not integration.gateway_server.memory_service:
            return {"ok": False, "error": "memory service unavailable"}

        memory_service = integration.gateway_server.memory_service
        uid = str(user_id or "default_user")

        if action == "stats":
            return {"ok": True, "stats": memory_service.get_sync_stats()}

        if not session_id:
            raise ValueError("session_id is required")

        if action == "search":
            context = await memory_service.get_context(query=query, session_id=session_id, user_id=uid)
            return {"ok": True, "session_id": session_id, "query": query, "context": context}

        if action == "cluster":
            result = await memory_service.cluster_entities(session_id=session_id, user_id=uid)
            return {"ok": True, "session_id": session_id, "result": result}

        if action == "summarize":
            result = await memory_service.summarize_session(session_id=session_id, user_id=uid, incremental=False)
            return {"ok": True, "session_id": session_id, "result": result}

        raise ValueError(f"unsupported memory action: {action}")

    async def message_action(
        self,
        action: str = "list_channels",
        channel: str = "",
        receiver_id: str = "",
        content: str = "",
    ) -> Dict[str, Any]:
        integration = get_gateway_integration()
        if not integration:
            return {"ok": False, "error": "gateway integration unavailable"}

        if action == "list_channels":
            registry = integration.get_channel_registry()
            status = registry.get_status_all() if registry else {}
            return {"ok": True, "channels": status, "total": len(status)}

        if action == "send":
            if not channel:
                raise ValueError("channel is required")
            if not content:
                raise ValueError("content is required")
            router = integration.get_message_router()
            if not router:
                return {"ok": False, "error": "message router unavailable"}
            await router.send_message(
                channel_name=channel,
                receiver_id=receiver_id or "default_user",
                content=content,
            )
            return {
                "ok": True,
                "sent": True,
                "channel": channel,
                "receiver_id": receiver_id or "default_user",
            }

        raise ValueError(f"unsupported message action: {action}")

    async def plugins_action(self, action: str = "list") -> Dict[str, Any]:
        registry = get_active_plugin_registry()
        if not registry:
            return {"ok": True, "total": 0, "plugins": []}

        if action == "list":
            plugins: List[Dict[str, Any]] = []
            for p in registry.plugins:
                plugins.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "kind": str(p.kind.value) if p.kind else "",
                        "enabled": bool(p.enabled),
                        "status": p.status,
                        "version": p.version,
                        "description": p.description,
                    }
                )
            return {"ok": True, "total": len(plugins), "plugins": plugins}

        if action == "diagnostics":
            rows = [d.model_dump() for d in registry.diagnostics]
            return {"ok": True, "total": len(rows), "diagnostics": rows}

        raise ValueError(f"unsupported plugins action: {action}")
