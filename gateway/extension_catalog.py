from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agentkit.mcp.mcp_manager import get_mcp_manager
from agentkit.mcp.mcpregistry import MANIFEST_CACHE, MANIFEST_SOURCES, reload_mcp_registry

from .official_tools import register_official_tools
from .tool_service import ToolService


OFFICIAL_MCP_ROOT = (Path(__file__).resolve().parents[1] / "agentkit" / "tools").resolve()
COMMUNITY_EXTENSION_ROOT = (Path(__file__).resolve().parents[1] / "extensions" / "community").resolve()


def ensure_extension_roots() -> None:
    COMMUNITY_EXTENSION_ROOT.mkdir(parents=True, exist_ok=True)


def ensure_tool_service(gateway_server: Any) -> Any:
    if getattr(gateway_server, "tool_service", None) is None:
        gateway_server.tool_service = ToolService(getattr(gateway_server, "event_emitter", None))
    register_official_tools(
        tool_service=gateway_server.tool_service,
        workspace_service=getattr(gateway_server, "workspace_service", None),
        memory_service=getattr(gateway_server, "memory_service", None),
        message_manager=getattr(gateway_server, "message_manager", None),
        gateway_server=gateway_server,
    )
    return gateway_server.tool_service


def _source_path(service_name: str) -> str:
    return str(MANIFEST_SOURCES.get(service_name) or "")


def _provider_for_manifest(service_name: str) -> str:
    raw = _source_path(service_name)
    if raw == "builtin":
        return "official"
    if not raw:
        return "community"
    try:
        source = Path(raw).resolve()
        if source.is_relative_to(OFFICIAL_MCP_ROOT):
            return "official"
        return "community"
    except Exception:
        return "community"


def _normalize_tool(
    *,
    tool_id: str,
    name: str,
    description: str,
    service_name: str,
    tool_type: str,
    domain: str,
    callable_now: bool = True,
    callable_reason: str = "callable",
    requires_confirmation: bool = False,
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "tool_id": tool_id,
        "name": name,
        "description": description,
        "service_name": service_name,
        "tool_name": name,
        "tool_type": tool_type,
        "domain": domain,
        "callable_now": callable_now,
        "callable_reason": callable_reason,
        "requires_confirmation": requires_confirmation,
        "input_schema": input_schema or {},
    }


def _grouped_extensions(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        extension_id = str(row.get("extension_id") or row.get("service_name") or row.get("tool_id") or "").strip()
        if not extension_id:
            continue
        current = grouped.setdefault(
            extension_id,
            {
                "id": extension_id,
                "name": str(row.get("extension_name") or extension_id),
                "provider": str(row.get("provider") or "community"),
                "source_type": str(row.get("source_type") or "unknown"),
                "description": str(row.get("extension_description") or row.get("description") or ""),
                "version": str(row.get("version") or ""),
                "source_path": str(row.get("source_path") or ""),
                "enabled": True,
                "status": str(row.get("status") or "ready"),
                "tools": [],
            },
        )
        current["tools"].append(row["tool"])

    out = list(grouped.values())
    for item in out:
        tools = item.get("tools") or []
        item["tool_count"] = len(tools)
        item["callable_count"] = sum(1 for tool in tools if bool(tool.get("callable_now", False)))
        if item["callable_count"] <= 0 and tools:
            item["status"] = "degraded"
    out.sort(key=lambda x: (str(x.get("provider") or ""), str(x.get("name") or "")))
    return out


async def build_extension_catalog(
    *,
    gateway_server: Any,
    user_id: Optional[str] = None,
    include_tools: bool = True,
) -> Dict[str, Any]:
    ensure_extension_roots()
    tool_service = ensure_tool_service(gateway_server)
    catalog = await tool_service.get_tool_catalog()

    rows: List[Dict[str, Any]] = []
    official_registered = getattr(tool_service, "_registered_tools", {}) or {}
    for tool_id, tool in official_registered.items():
        if not bool(getattr(tool, "official", False)):
            continue
        domain = str(getattr(tool, "official_domain", "misc") or "misc")
        rows.append(
            {
                "extension_id": f"official.{domain}",
                "extension_name": f"Official {domain}",
                "provider": "official",
                "source_type": "official_tools",
                "extension_description": f"Built-in {domain} tools.",
                "status": "ready",
                "tool": _normalize_tool(
                    tool_id=str(tool_id),
                    name=str(getattr(tool, "name", tool_id)),
                    description=str(getattr(tool, "description", "")),
                    service_name=str(tool_id),
                    tool_type="local",
                    domain=domain,
                ),
            }
        )

    by_key = {
        (str(item.get("service_name") or ""), str(item.get("tool_name") or "")): item
        for item in catalog
    }
    health_by_service = {
        str(row.get("service_name") or ""): row
        for row in (get_mcp_manager().list_service_health(user_id=user_id) or [])
        if isinstance(row, dict)
    }
    for service_name, manifest in MANIFEST_CACHE.items():
        if service_name == "builtin":
            continue
        provider = _provider_for_manifest(service_name)
        source_path = _source_path(service_name)
        health = health_by_service.get(str(service_name), {})
        status = str(health.get("status") or "ready")
        commands = (((manifest or {}).get("capabilities") or {}).get("invocation_commands") or [])
        if not commands:
            commands = [{"command": service_name, "description": str((manifest or {}).get("description") or "")}]
        for command in commands:
            if not isinstance(command, dict):
                continue
            command_name = str(command.get("command") or service_name)
            catalog_row = by_key.get((str(service_name), command_name), {})
            rows.append(
                {
                    "extension_id": str(service_name),
                    "extension_name": str((manifest or {}).get("label") or service_name),
                    "provider": provider,
                    "source_type": "mcp_manifest",
                    "extension_description": str((manifest or {}).get("description") or ""),
                    "version": str((manifest or {}).get("version") or ""),
                    "source_path": source_path,
                    "status": status,
                    "tool": _normalize_tool(
                        tool_id=f"{service_name}.{command_name}",
                        name=command_name,
                        description=str(command.get("description") or (manifest or {}).get("description") or ""),
                        service_name=str(service_name),
                        tool_type="mcp",
                        domain=str((manifest or {}).get("category") or "mcp"),
                        callable_now=bool(catalog_row.get("callable_now", status not in {"offline", "hidden"})),
                        callable_reason=str(catalog_row.get("callable_reason") or status or "callable"),
                        requires_confirmation=bool(catalog_row.get("requires_confirmation", False)),
                        input_schema=dict((manifest or {}).get("inputSchema") or {}),
                    ),
                }
            )

    extensions = _grouped_extensions(rows)
    if not include_tools:
        for item in extensions:
            item.pop("tools", None)
    return {
        "status": "success",
        "roots": {
            "official": str(OFFICIAL_MCP_ROOT),
            "community": str(COMMUNITY_EXTENSION_ROOT),
        },
        "total": len(extensions),
        "extensions": extensions,
    }


def reload_extensions() -> Dict[str, Any]:
    ensure_extension_roots()
    roots = [str(OFFICIAL_MCP_ROOT), str(COMMUNITY_EXTENSION_ROOT)]
    registered = reload_mcp_registry(roots)
    manager = get_mcp_manager()
    manager.tools_cache.clear()
    return {
        "status": "success",
        "registered": registered,
        "roots": {"official": roots[0], "community": roots[1]},
    }
