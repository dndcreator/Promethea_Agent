"""External MCP provider configuration, not the Runtime tool registry."""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List



MCP_REGISTRY = {}
MANIFEST_CACHE = {}
MANIFEST_SOURCES = {}

def _external_mcp_config(manifest: Dict[str, Any], manifest_path: Path) -> Dict[str, Any]:
    transport = manifest.get("transport") or {}
    if not isinstance(transport, dict) or str(transport.get("type") or "stdio") != "stdio":
        raise ValueError("external MCP manifest requires a stdio transport")
    command = str(transport.get("command") or "").strip()
    args = transport.get("args") or []
    if not command or not isinstance(args, list):
        raise ValueError("external MCP stdio transport requires command and args")
    cwd = str(transport.get("cwd") or "").strip()
    if cwd and not Path(cwd).is_absolute():
        cwd = str((manifest_path.parent / cwd).resolve())
    env = transport.get("env") or {}
    if not isinstance(env, dict):
        raise ValueError("external MCP transport env must be an object")
    return {
        "transport": "stdio",
        "command": command,
        "args": [str(item) for item in args],
        "cwd": cwd or None,
        "env": {str(key): str(value) for key, value in env.items()},
    }

def get_service_info(service_name: str) -> Optional[Dict[str, Any]]:

    if service_name not in MCP_REGISTRY:
        return None

    manifest = MANIFEST_CACHE.get(service_name, {})
    instance = MCP_REGISTRY.get(service_name)

    return {
        "name": service_name,
        "manifest": manifest,
        "instance": instance,
        "description": manifest.get('description', ''),
        "label": manifest.get('label', service_name),
        "version": manifest.get('version', '1.0.0'),
        "capabilities": manifest.get('capabilities', {}),
        "input_schema": manifest.get('inputSchema', {}),
        "available_tools": get_available_tools(service_name)
    }

def get_available_tools(service_name: str) -> List[Dict[str, Any]]:

    if service_name not in MCP_REGISTRY:
        return []
    manifest = MANIFEST_CACHE.get(service_name, {})
    capabilities = manifest.get('capabilities', {})
    invocation_commands = capabilities.get("invocation_commands", [])

    tools = []
    for command in invocation_commands:
        tools.append({
            "name": command.get('command', ''),
            "description": command.get('description', ''),
            "example": command.get('example', ''),
            "input_schema": manifest.get('inputSchema', {}),
            "requires_capability": command.get('requiresCapability'),
            "requires_config": command.get('requiresConfig'),
            "owner_user_id": command.get('ownerUserId'),
            "side_effect_level": command.get('sideEffectLevel'),
            "side_effect_selector": command.get('sideEffectSelector'),
            "presentation": command.get('presentation') or manifest.get('presentation') or {},
        })
    return tools

def get_all_services_info() -> Dict[str, Any]:

    services_info = {}
    for service_name in MCP_REGISTRY.keys():
        service_info = get_service_info(service_name)
        if service_info:
            services_info[service_name] = service_info
    
    return services_info

def reload_mcp_registry(scan_dirs: Optional[List[str]] = None) -> List[str]:
    """Validate provider configurations before replacing the selected roots."""
    roots = [Path(x or "agentkit").resolve() for x in (scan_dirs or ["agentkit"])]
    removed = set()
    for service_name, source in list(MANIFEST_SOURCES.items()):
        try:
            source_path = Path(source).resolve()
            if any(source_path.is_relative_to(root) for root in roots):
                removed.add(service_name)
        except Exception:
            continue
    staged = {}
    paths = sorted({path.resolve() for root in roots if root.exists() for path in root.glob("**/agent-manifest.json")})
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError(f"MCP manifest must contain an object: {path}")
        if manifest.get("serviceType") != "mcp" or manifest.get("entryPoint") or manifest.get("generatedCapability"):
            continue
        name = str(manifest.get("name") or "").strip()
        if not name:
            raise ValueError(f"MCP manifest is missing name: {path}")
        if name in staged or (name in MCP_REGISTRY and name not in removed):
            raise ValueError(f"duplicate MCP provider name: {name}")
        staged[name] = (manifest, _external_mcp_config(manifest, path), str(path))

    for service_name in removed:
        MCP_REGISTRY.pop(service_name, None)
        MANIFEST_CACHE.pop(service_name, None)
        MANIFEST_SOURCES.pop(service_name, None)
    for name, (manifest, config, source) in staged.items():
        MCP_REGISTRY[name] = config
        MANIFEST_CACHE[name] = manifest
        MANIFEST_SOURCES[name] = source
    return list(staged)

if __name__ == "__main__":
    reload_mcp_registry()
