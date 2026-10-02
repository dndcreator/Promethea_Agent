from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from agentkit.mcp.mcp_manager import get_mcp_manager
from agentkit.mcp.mcpregistry import reload_mcp_registry

from .official_tools import register_official_tools


OFFICIAL_TOOL_ROOT = (Path(__file__).resolve().parents[1] / "agentkit" / "tools").resolve()
COMMUNITY_EXTENSION_ROOT = (Path(__file__).resolve().parents[1] / "extensions" / "community").resolve()


def ensure_extension_roots() -> None:
    COMMUNITY_EXTENSION_ROOT.mkdir(parents=True, exist_ok=True)


def ensure_capability_service(gateway_server: Any) -> Any:
    capability_service = gateway_server.ensure_capability_service()
    register_official_tools(
        capability_service=capability_service,
        workspace_service=getattr(gateway_server, "workspace_service", None),
        memory_service=getattr(gateway_server, "memory_service", None),
        message_manager=getattr(gateway_server, "message_manager", None),
        gateway_server=gateway_server,
    )
    return capability_service

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
    capability_service = ensure_capability_service(gateway_server)
    user_config = None
    config_service = getattr(gateway_server, "config_service", None)
    if config_service is not None and user_id:
        merged = config_service.get_merged_config(user_id)
        user_config = merged if isinstance(merged, dict) else None
    catalog = await capability_service.get_tool_catalog(
        run_context=SimpleNamespace(user_id=user_id) if user_id else None,
        user_config=user_config,
    )

    rows: List[Dict[str, Any]] = []
    by_key = {
        (str(item.get("service_name") or ""), str(item.get("tool_name") or "")): item
        for item in catalog
    }
    registered = getattr(capability_service, "_registered_tools", {}) or {}
    for tool_id, tool in registered.items():
        spec = capability_service.tool_registry.resolve(tool_name=str(tool_id), params={})
        metadata = dict(spec.metadata or {})
        is_extension = str(spec.source.value) == "extension"
        domain = str(getattr(tool, "official_domain", "misc") or "misc")
        extension_id = str(metadata.get("extension_id") or (f"official.{domain}" if not is_extension else domain))
        service_name = str(spec.service_name or tool_id)
        tool_name = str(spec.tool_name or tool_id)
        catalog_row = by_key.get((service_name, tool_name)) or by_key.get((str(tool_id), str(tool_id))) or {}
        rows.append(
            {
                "extension_id": extension_id,
                "extension_name": str(metadata.get("extension_name") or (f"Official {domain}" if not is_extension else extension_id)),
                "provider": "community" if is_extension else "official",
                "source_type": "manifest_tool" if metadata.get("manifest_path") else "official_tools",
                "extension_description": str(getattr(tool, "description", "")),
                "version": str(metadata.get("extension_version") or ""),
                "source_path": str(metadata.get("manifest_path") or ""),
                "status": "ready" if bool(catalog_row.get("callable_now", True)) else "degraded",
                "tool": _normalize_tool(
                    tool_id=str(tool_id),
                    name=tool_name,
                    description=str(getattr(tool, "description", "")),
                    service_name=service_name,
                    tool_type=str(spec.source.value),
                    domain=domain,
                    callable_now=bool(catalog_row.get("callable_now", True)),
                    callable_reason=str(catalog_row.get("callable_reason") or "callable"),
                    requires_confirmation=bool(catalog_row.get("requires_confirmation", False)),
                    input_schema=dict(spec.input_schema or {}),
                ),
            }
        )

    manager = get_mcp_manager()
    for spec in capability_service.tool_registry.list_specs():
        if str(spec.source.value) != "mcp" or bool(spec.metadata.get("inferred")):
            continue
        service_name = str(spec.service_name or spec.tool_name)
        tool_name = str(spec.tool_name)
        provider_info = manager.query_service_by_name(service_name) or {}
        catalog_row = by_key.get((service_name, tool_name), {})
        rows.append(
            {
                "extension_id": service_name,
                "extension_name": str(provider_info.get("label") or service_name),
                "provider": "external",
                "source_type": "mcp",
                "extension_description": str(provider_info.get("description") or spec.description),
                "version": str(provider_info.get("version") or ""),
                "source_path": "",
                "status": "ready" if bool(catalog_row.get("callable_now", False)) else "degraded",
                "tool": _normalize_tool(
                    tool_id=spec.full_name,
                    name=tool_name,
                    description=spec.description,
                    service_name=service_name,
                    tool_type="mcp",
                    domain="mcp",
                    callable_now=bool(catalog_row.get("callable_now", False)),
                    callable_reason=str(catalog_row.get("callable_reason") or "provider_unavailable"),
                    requires_confirmation=bool(catalog_row.get("requires_confirmation", True)),
                    input_schema=dict(spec.input_schema or {}),
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
            "official": str(OFFICIAL_TOOL_ROOT),
            "community": str(COMMUNITY_EXTENSION_ROOT),
        },
        "total": len(extensions),
        "extensions": extensions,
    }


async def reload_extensions(gateway_server: Any) -> Dict[str, Any]:
    ensure_extension_roots()
    roots = [str(OFFICIAL_TOOL_ROOT), str(COMMUNITY_EXTENSION_ROOT)]
    capability_service = ensure_capability_service(gateway_server)
    registered = capability_service.reload_discovered_tools(roots, reload_modules=True)
    manager = get_mcp_manager()
    await manager.clean_services()
    external = reload_mcp_registry(roots)
    return {
        "status": "success",
        "registered": registered,
        "external_mcp": external,
        "roots": {"official": roots[0], "community": roots[1]},
    }
