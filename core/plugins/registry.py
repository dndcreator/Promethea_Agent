from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from loguru import logger

from .types import PluginRegistry, ChannelEntry, ServiceEntry, PluginRecord


class PluginApi:
    def __init__(self, registry: PluginRegistry, plugin: PluginRecord, plugin_config: Optional[Dict[str, Any]] = None):
        self._registry = registry
        self.plugin = plugin
        self.config = plugin_config or {}

    def register_channel(self, channel_id: str, channel: Any) -> None:
        self._registry.channels.append(ChannelEntry(channel_id=channel_id, channel=channel, source=self.plugin.source))
        logger.info(f"[plugins] registered channel: {channel_id} (plugin={self.plugin.id})")

    def register_service(self, service_id: str, service: Any) -> None:
        self._registry.services.append(ServiceEntry(service_id=service_id, service=service, source=self.plugin.source))
        logger.info(f"[plugins] registered service: {service_id} (plugin={self.plugin.id})")


def create_plugin_registry() -> Tuple[PluginRegistry, Any]:
    registry = PluginRegistry()

    def create_api(plugin: PluginRecord, plugin_config: Optional[Dict[str, Any]] = None) -> PluginApi:
        return PluginApi(registry, plugin, plugin_config)

    return registry, create_api


def find_channel(channel_id: str) -> Optional[Any]:
    from .runtime import require_active_plugin_registry

    reg = require_active_plugin_registry()
    for entry in reg.channels:
        if entry.channel_id == channel_id:
            return entry.channel
    return None


def find_service(service_id: str) -> Optional[Any]:
    from .runtime import require_active_plugin_registry

    reg = require_active_plugin_registry()
    for entry in reg.services:
        if entry.service_id == service_id:
            return entry.service
    return None

