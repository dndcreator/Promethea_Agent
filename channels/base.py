"""
"""
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from loguru import logger

class ChannelType(str, Enum):
    """TODO: add docstring."""
    WEB = "web"              # TODO: comment cleaned
    DINGTALK = "dingtalk"
    FEISHU = "feishu"        # TODO: comment cleaned
    WECOM = "wecom"
    WECHAT = "wechat"        # WeChat (for testing)
    QQ = "qq"                # QQ (for testing)
    API = "api"              # REST API
    WEBHOOK = "webhook"      # Webhook
    

class MessageType(str, Enum):
    """TODO: add docstring."""
    TEXT = "text"
    MARKDOWN = "markdown"
    CARD = "card"
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    LINK = "link"
    

class Message(BaseModel):
    """TODO: add docstring."""
    message_id: str
    channel: ChannelType
    message_type: MessageType = MessageType.TEXT
    
    sender_id: str
    sender_name: Optional[str] = None
    
    receiver_id: str           # User ID or group ID
    receiver_type: str = "user"  # user, group, channel
    
    content: str
    raw_content: Optional[Dict[str, Any]] = None  # Original message payload
    
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    reply_to: Optional[str] = None
    thread_id: Optional[str] = None


class ChannelConfig(BaseModel):
    """TODO: add docstring."""
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    api_endpoint: Optional[str] = None
    token: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class BaseChannel(ABC):
    """TODO: add docstring."""
    
    def __init__(self, channel_name: str, channel_type: ChannelType, config: ChannelConfig):
        self.channel_name = channel_name
        self.channel_type = channel_type
        self.config = config
        self.is_connected = False
        self.is_running = False
        
        self.logger = logger.bind(channel=self.channel_name)

        self._on_message_callbacks: List[Callable] = []
        self._on_event_callbacks: List[Callable] = []
        
    
    @abstractmethod
    async def connect(self) -> bool:
        """TODO: add docstring."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """TODO: add docstring."""
        pass
    
    @abstractmethod
    async def send_message(
        self,
        receiver_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        """TODO: add docstring."""
        pass
    
    @abstractmethod
    async def send_card(
        self,
        receiver_id: str,
        card_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """TODO: add docstring."""
        pass
    
    
    async def start(self) -> bool:
        """TODO: add docstring."""
        if self.is_running:
            logger.warning(f"Channel {self.channel_name} is already running")
            return True
        
        try:
            if not self.config.enabled:
                logger.info(f"Channel {self.channel_name} is disabled")
                return False
            
            connected = await self.connect()
            if connected:
                self.is_running = True
                self.is_connected = True
                logger.info(f"Channel {self.channel_name} started successfully")
                return True
            else:
                logger.error(f"Failed to connect channel {self.channel_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error starting channel {self.channel_name}: {e}")
            return False
    
    async def stop(self) -> bool:
        """TODO: add docstring."""
        if not self.is_running:
            return True
        
        try:
            await self.disconnect()
            self.is_running = False
            self.is_connected = False
            logger.info(f"Channel {self.channel_name} stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping channel {self.channel_name}: {e}")
            return False
    
    def on_message(self, callback: Callable):
        """TODO: add docstring."""
        if callback not in self._on_message_callbacks:
            self._on_message_callbacks.append(callback)
    
    def on_event(self, callback: Callable):
        """TODO: add docstring."""
        if callback not in self._on_event_callbacks:
            self._on_event_callbacks.append(callback)
    
    async def _emit_message(self, message: Message):
        """TODO: add docstring."""
        for callback in self._on_message_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")
    
    async def _emit_event(self, event_type: str, event_data: Dict[str, Any]):
        """TODO: add docstring."""
        for callback in self._on_event_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, event_data)
                else:
                    callback(event_type, event_data)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """TODO: add docstring."""
        return {
            "channel_name": self.channel_name,
            "channel_type": self.channel_type,
            "is_connected": self.is_connected,
            "is_running": self.is_running,
            "enabled": self.config.enabled,
        }
    
    async def validate_config(self) -> bool:
        if not self.config.enabled:
            return True
