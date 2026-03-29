from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.tool_service import ToolInvocationContext


class RuntimeServicesTool:
    tool_id = "runtime.services"
    name = "runtime.services"
    description = "Return gateway service health snapshot."
    official = True
    official_domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = args, ctx
        health = self.gateway_server.get_services_health()
        overall = "healthy" if all(bool(v) for v in health.values()) else "degraded"
        return {"status": overall, "services": health}


class RuntimeProcessingStatsTool:
    tool_id = "runtime.processing_stats"
    name = "runtime.processing_stats"
    description = "Return conversation processing stats."
    official = True
    official_domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = args, ctx
        svc = getattr(self.gateway_server, "conversation_service", None)
        if not svc:
            return {"ok": False, "reason": "conversation_service_unavailable"}
        return {"ok": True, "stats": svc.get_processing_stats()}


class RuntimeListToolsTool:
    tool_id = "runtime.list_tools"
    name = "runtime.list_tools"
    description = "List registered tools and optionally filter official-only."
    official = True
    official_domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        official_only = bool((args or {}).get("official_only", False))
        tool_service = getattr(self.gateway_server, "tool_service", None)
        if tool_service is None:
            return {"ok": False, "reason": "tool_service_unavailable", "count": 0, "tools": []}
        rows = []
        for tool_id, tool in (getattr(tool_service, "_registered_tools", {}) or {}).items():
            if official_only and not bool(getattr(tool, "official", False)):
                continue
            rows.append(
                {
                    "tool_id": tool_id,
                    "name": str(getattr(tool, "name", tool_id)),
                    "description": str(getattr(tool, "description", "")),
                    "official": bool(getattr(tool, "official", False)),
                    "domain": str(getattr(tool, "official_domain", "misc") or "misc"),
                }
            )
        rows.sort(key=lambda x: (x.get("domain", ""), x.get("tool_id", "")))
        return {"ok": True, "count": len(rows), "tools": rows}
