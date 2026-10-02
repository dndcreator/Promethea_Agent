from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .spec import ToolSource


SUPPORTED_SERVICE_TYPES = {"mcp", "tool", "internal_tool", "extension_tool"}


@dataclass(frozen=True)
class DiscoveredTool:
    tool: Any
    manifest: Dict[str, Any]
    manifest_path: Path


class ManifestTool:
    """Adapt one manifest command to the canonical in-process Tool protocol."""

    def __init__(
        self,
        *,
        service_name: str,
        service: Any,
        command: Dict[str, Any],
        manifest: Dict[str, Any],
        manifest_path: Path,
        source: ToolSource,
    ) -> None:
        command_name = str(command.get("command") or "").strip()
        if not command_name:
            raise ValueError(f"tool command is missing in {manifest_path}")
        method = getattr(service, command_name, None)
        if not callable(method):
            raise AttributeError(f"tool entry point is missing method {service_name}.{command_name}")

        self.tool_id = f"{service_name}.{command_name}"
        self.name = self.tool_id
        self.description = str(command.get("description") or manifest.get("description") or "")
        self.input_schema = dict(command.get("inputSchema") or manifest.get("inputSchema") or {})
        self.output_schema = dict(command.get("outputSchema") or manifest.get("outputSchema") or {})
        self.side_effect_level = str(command.get("sideEffectLevel") or "privileged_host_action")
        self.side_effect_selector = dict(command.get("sideEffectSelector") or {})
        self.requires_capability = str(command.get("requiresCapability") or "").strip()
        self.requires_config = command.get("requiresConfig")
        self.owner_user_id = str(
            command.get("ownerUserId")
            or (manifest.get("generatedCapability") or {}).get("ownerUserId")
            or ""
        ).strip()
        self.timeout_ms = int(command.get("timeoutMs") or manifest.get("timeoutMs") or 30000)
        self.retry_policy = dict(command.get("retryPolicy") or manifest.get("retryPolicy") or {"max_retries": 0})
        self.idempotency_hint = str(command.get("idempotencyHint") or "unknown")
        self.tool_source = source
        self.official = source == ToolSource.LOCAL
        self.official_domain = str(manifest.get("category") or service_name)
        self.extension_id = service_name
        self.extension_name = str(manifest.get("label") or service_name)
        self.extension_version = str(manifest.get("version") or "")
        self.manifest_path = str(manifest_path.resolve())
        self._method = method

    async def invoke(self, args: Dict[str, Any], ctx: Optional[Any] = None) -> Any:
        _ = ctx
        parameters = inspect.signature(self._method).parameters
        accepts_extra = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        payload = {
            key: value
            for key, value in dict(args or {}).items()
            if key not in {"agentType", "service_name", "tool_name"}
            and (accepts_extra or key in parameters)
        }
        result = self._method(**payload)
        return await result if inspect.isawaitable(result) else result


def _load_manifest(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"tool manifest must contain an object: {path}")
    return payload


def _load_service(manifest: Dict[str, Any], manifest_path: Path, *, reload_modules: bool) -> Any:
    generated = manifest.get("generatedCapability")
    if isinstance(generated, dict):
        from agentkit.tools.self_evolve.generated_runtime import GeneratedCapabilityService

        return GeneratedCapabilityService(manifest=manifest, manifest_path=manifest_path)

    entry_point = manifest.get("entryPoint") or {}
    module_name = str(entry_point.get("module") or "").strip()
    class_name = str(entry_point.get("class") or "").strip()
    if not module_name or not class_name:
        raise ValueError(f"in-process tool manifest is missing entryPoint: {manifest_path}")
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    if reload_modules:
        module = importlib.reload(module)
    service_class = getattr(module, class_name)
    return service_class()


def _source_for(path: Path, official_root: Path) -> ToolSource:
    try:
        path.resolve().relative_to(official_root.resolve())
        return ToolSource.LOCAL
    except ValueError:
        return ToolSource.EXTENSION


def discover_manifest_tools(
    roots: Iterable[Path],
    *,
    official_root: Path,
    reload_modules: bool = False,
) -> List[DiscoveredTool]:
    """Scan manifests and stage a complete tool snapshot before registration."""
    discovered: List[DiscoveredTool] = []
    seen_ids: Dict[str, Path] = {}
    for root in (Path(item).resolve() for item in roots):
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("**/agent-manifest.json")):
            manifest = _load_manifest(manifest_path)
            service_type = str(manifest.get("serviceType") or "").strip()
            if service_type not in SUPPORTED_SERVICE_TYPES:
                continue
            # A true external MCP provider is connected by MCPManager. Manifests
            # with Python entry points are local or extension tools.
            if not manifest.get("entryPoint") and not manifest.get("generatedCapability"):
                continue
            service_name = str(manifest.get("name") or "").strip()
            if not service_name:
                raise ValueError(f"tool manifest is missing name: {manifest_path}")
            service = _load_service(manifest, manifest_path, reload_modules=reload_modules)
            commands = ((manifest.get("capabilities") or {}).get("invocation_commands") or [])
            if not isinstance(commands, list) or not commands:
                raise ValueError(f"tool manifest has no invocation commands: {manifest_path}")
            source = _source_for(manifest_path, official_root)
            for command in commands:
                if not isinstance(command, dict):
                    raise ValueError(f"invalid tool command in {manifest_path}")
                tool = ManifestTool(
                    service_name=service_name,
                    service=service,
                    command=command,
                    manifest=manifest,
                    manifest_path=manifest_path,
                    source=source,
                )
                previous = seen_ids.get(tool.tool_id)
                if previous is not None:
                    raise ValueError(f"duplicate tool id {tool.tool_id}: {previous} and {manifest_path}")
                seen_ids[tool.tool_id] = manifest_path
                discovered.append(DiscoveredTool(tool=tool, manifest=manifest, manifest_path=manifest_path))
    return discovered
