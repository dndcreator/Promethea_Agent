from __future__ import annotations

from typing import Dict, Optional

from .adapter_framework import ChannelAdapter
from .adapters.http_adapter import HttpApiChannelAdapter
from .adapters.telegram_adapter import TelegramChannelAdapter
from .adapters.web_adapter import WebChannelAdapter


class ChannelAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        self._adapters[adapter.metadata.channel_id] = adapter

    def get(self, channel_id: str) -> Optional[ChannelAdapter]:
        return self._adapters.get(str(channel_id or "").strip())

    def list_metadata(self) -> list[dict]:
        return [adapter.metadata.model_dump() for adapter in self._adapters.values()]


def build_default_adapter_registry() -> ChannelAdapterRegistry:
    registry = ChannelAdapterRegistry()
    registry.register(WebChannelAdapter())
    registry.register(HttpApiChannelAdapter())
    registry.register(TelegramChannelAdapter())
    return registry
