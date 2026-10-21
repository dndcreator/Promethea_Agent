from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from gateway.capability_service import ToolInvocationContext
from gateway.tools.schema import input_object, integer, text
from gateway.protocol import EventType


class RuntimeReadObservationTool:
    input_schema = input_object({
        "observation_id": text(), "field": text(enum=("result", "error")),
        "offset": integer(minimum=0), "max_chars": integer(minimum=100, maximum=16000),
    }, required=("observation_id",))
    tool_id = name = "runtime.read_observation"
    description = "Read a retained Runtime observation in bounded text pages."
    side_effect_level = "read_only"
    concurrency_safe = True
    domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id = str(ctx.user_id or "") if ctx else ""
        if not user_id:
            raise PermissionError("observation reads require an authenticated owner")
        emitter = getattr(self.gateway_server, "event_emitter", None)
        log = getattr(emitter, "event_log", None)
        if log is None:
            raise RuntimeError("Runtime observation storage is unavailable")
        observation_id = str(args.get("observation_id") or "").strip()
        if not observation_id:
            raise ValueError("observation_id is required")
        rows = await asyncio.to_thread(log.query, user_id=user_id, observation_id=observation_id,
                                       event_type=EventType.ACTION_OBSERVATION_COMMITTED.value, limit=1)
        if not rows:
            raise FileNotFoundError("observation is not available in retained owner history")
        payload = rows[0]["payload"]
        field = str(args.get("field") or "result")
        if field not in {"result", "error"}:
            raise ValueError("field must be result or error")
        value = payload.get("error") if field == "error" else payload.get("structured_result")
        if field == "result" and value is None:
            projection = payload.get("model_projection", [])
            value = projection if isinstance(projection, dict) else "\n".join(str(block.get("text") or "") for block in projection if block.get("type") == "text")
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        offset = max(0, int(args.get("offset") or 0))
        maximum = max(100, min(16000, int(args.get("max_chars") or 8000)))
        end = min(len(encoded), offset + maximum)
        return {"observation_id": observation_id, "field": field, "offset": offset, "total_chars": len(encoded),
                "content": encoded[offset:end], "next_offset": end if end < len(encoded) else None,
                "source_truncated": isinstance(value, dict) and value.get("truncated") is True}


class RuntimeServicesTool:
    input_schema = input_object()
    tool_id = "runtime.services"
    side_effect_level = "read_only"
    name = "runtime.services"
    description = "Return gateway service health snapshot."
    domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = args, ctx
        health = self.gateway_server.get_services_health()
        healthy = [name for name, ready in health.items() if bool(ready)]
        unhealthy = [name for name, ready in health.items() if not bool(ready)]
        overall = "healthy" if not unhealthy else "degraded"
        return {
            "status": overall,
            "service_count": len(health),
            "healthy_count": len(healthy),
            "unhealthy_services": unhealthy,
            "services": health,
        }


class RuntimeProcessingStatsTool:
    input_schema = input_object()
    tool_id = "runtime.processing_stats"
    side_effect_level = "read_only"
    name = "runtime.processing_stats"
    description = "Return conversation processing stats."
    domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = args, ctx
        svc = getattr(self.gateway_server, "conversation_service", None)
        if not svc:
            return {"ok": False, "reason": "conversation_service_unavailable"}
        return {"ok": True, "stats": svc.get_processing_stats()}


class RuntimeListToolsTool:
    input_schema = input_object({"domain": text(), "tool_id": text()})
    tool_id = "runtime.list_tools"
    side_effect_level = "read_only"
    name = "runtime.list_tools"
    description = "List registered tools, optionally filtered by domain or canonical tool id."
    domain = "runtime"

    def __init__(self, *, gateway_server: Any) -> None:
        self.gateway_server = gateway_server

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        capability_service = getattr(self.gateway_server, "capability_service", None)
        if capability_service is None:
            return {"ok": False, "reason": "capability_service_unavailable", "count": 0, "tools": []}
        rows = []
        catalog = await capability_service.get_tool_catalog(run_context=ctx)
        domain_filter = str((args or {}).get("domain") or "").strip()
        id_filter = str((args or {}).get("tool_id") or "").strip()
        for entry in catalog:
            spec = capability_service.tool_registry.resolve(
                tool_name=entry["tool_name"], params=entry,
            )
            tool_id = spec.full_name
            tool = capability_service._registered_tools.get(tool_id)
            domain = str(getattr(tool, "domain", None) or spec.service_name or "misc")
            if (domain_filter and domain != domain_filter) or (id_filter and tool_id != id_filter):
                continue
            rows.append(
                {
                    "tool_id": tool_id,
                    "name": tool_id,
                    "description": spec.description,
                    "domain": domain,
                    "callable_now": entry["callable_now"],
                    "callable_reason": entry["callable_reason"],
                    "requires_confirmation": entry["requires_confirmation"],
                }
            )
        rows.sort(key=lambda x: (x.get("domain", ""), x.get("tool_id", "")))
        return {
            "ok": True,
            "count": len(rows),
            "tools": rows,
        }
