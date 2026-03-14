"""
"""
from .base import BaseChannel, ChannelType, ChannelConfig, Message, MessageType
from .registry import ChannelRegistry
from .router import MessageRouter
from .adapter_framework import ChannelAdapter, ChannelMetadata, IdentityContext, PermissionDecision
from .adapter_registry import ChannelAdapterRegistry, build_default_adapter_registry

__all__ = [
    "BaseChannel",
    "ChannelType",
    "ChannelConfig",
    "Message",
    "MessageType",
    "ChannelRegistry",
    "MessageRouter",
    "ChannelAdapter",
    "ChannelMetadata",
    "IdentityContext",
    "PermissionDecision",
    "ChannelAdapterRegistry",
    "build_default_adapter_registry",
]


