from __future__ import annotations

from typing import Optional

from .types import PluginRegistry


_active_registry: Optional[PluginRegistry] = PluginRegistry()
_active_key: Optional[str] = None


def set_active_plugin_registry(registry: PluginRegistry, cache_key: Optional[str] = None) -> None:
    global _active_registry, _active_key
    _active_registry = registry
    _active_key = cache_key


def get_active_plugin_registry() -> Optional[PluginRegistry]:
    return _active_registry


def require_active_plugin_registry() -> PluginRegistry:
    global _active_registry
    if _active_registry is None:
        _active_registry = PluginRegistry()
    return _active_registry


def get_active_plugin_registry_key() -> Optional[str]:
    return _active_key

