from __future__ import annotations

import hashlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger

from .discovery import discover_promethea_plugins
from .manifest import load_plugin_manifest
from .registry import create_plugin_registry
from .runtime import set_active_plugin_registry
from .types import PluginDiagnostic, PluginRecord, PluginRegistry


@dataclass
class PluginLoadOptions:
    workspace_dir: str
    extensions_dir: str = "extensions"
    config: Optional[Dict[str, Any]] = None
    cache: bool = True
    mode: str = "full"  # full|validate
    allow: Optional[set[str]] = None  # allowlist by plugin id


_registry_cache: Dict[str, PluginRegistry] = {}


def _build_cache_key(workspace_dir: str, cfg: Dict[str, Any]) -> str:
    raw = f"{os.path.abspath(workspace_dir)}::{cfg}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_promethea_plugins(options: PluginLoadOptions) -> PluginRegistry:
    cfg = options.config or {}
    cache_key = _build_cache_key(options.workspace_dir, cfg)
    if options.cache and cache_key in _registry_cache:
        reg = _registry_cache[cache_key]
        set_active_plugin_registry(reg, cache_key)
        return reg

    registry, create_api = create_plugin_registry()

    candidates = discover_promethea_plugins(options.workspace_dir, options.extensions_dir)
    plugins_cfg: Dict[str, Any] = (cfg.get("plugins") or {}) if isinstance(cfg, dict) else {}

    for cand in candidates:
        ok, manifest_path, manifest_or_err = load_plugin_manifest(cand.root_dir)
        if not ok:
            registry.diagnostics.append(
                PluginDiagnostic(level="error", source=manifest_path, message=str(manifest_or_err))
            )
            continue

        manifest = manifest_or_err  # type: ignore[assignment]
        plugin_id = manifest.id

        if options.allow is not None and plugin_id not in options.allow:
            registry.plugins.append(
                PluginRecord(
                    id=plugin_id,
                    source=cand.source,
                    enabled=False,
                    status="disabled",
                    error="blocked by allowlist",
                    kind=manifest.kind,
                    name=manifest.name,
                    description=manifest.description,
                    version=manifest.version,
                )
            )
            continue

        entry_cfg = plugins_cfg.get(plugin_id) if isinstance(plugins_cfg, dict) else None
        enabled = True
        plugin_config: Dict[str, Any] = {}
        if isinstance(entry_cfg, dict):
            enabled = bool(entry_cfg.get("enabled", True))
            plugin_config = entry_cfg.get("config") or {}

        record = PluginRecord(
            id=plugin_id,
            source=cand.source,
            enabled=enabled,
            status="loaded" if enabled else "disabled",
            kind=manifest.kind,
            name=manifest.name,
            description=manifest.description,
            version=manifest.version,
        )
        registry.plugins.append(record)

        if not enabled:
            continue

        if options.mode == "validate":
            continue

        # Load plugin module from source file
        try:
            module_name = f"promethea_ext_{plugin_id}"
            spec = importlib.util.spec_from_file_location(module_name, cand.source)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"failed to create module spec for {cand.source}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        except Exception as e:
            record.status = "error"
            record.error = f"failed to load plugin module: {e}"
            registry.diagnostics.append(
                PluginDiagnostic(level="error", plugin_id=plugin_id, source=cand.source, message=record.error)
            )
            continue

        # Resolve register() function (Moltbot: default export or function export)
        register = getattr(mod, "register", None) or getattr(mod, "activate", None)
        if not callable(register):
            record.status = "error"
            record.error = "plugin export missing register/activate"
            registry.diagnostics.append(
                PluginDiagnostic(level="error", plugin_id=plugin_id, source=cand.source, message=record.error)
            )
            continue

        api = create_api(record, plugin_config)
        try:
            register(api)
        except Exception as e:
            record.status = "error"
            record.error = f"plugin failed during register: {e}"
            registry.diagnostics.append(
                PluginDiagnostic(level="error", plugin_id=plugin_id, source=cand.source, message=record.error)
            )

    if options.cache:
        _registry_cache[cache_key] = registry

    set_active_plugin_registry(registry, cache_key)
    return registry

