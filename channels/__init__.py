"""
通道系统 - 多平台消息通道抽象
"""
from .base import BaseChannel, ChannelType, ChannelConfig, Message, MessageType
from .registry import ChannelRegistry
from .router import MessageRouter

__all__ = [
    "BaseChannel",
    "ChannelType",
    "ChannelConfig",
    "Message",
    "MessageType",
    "ChannelRegistry",
    "MessageRouter",
]
