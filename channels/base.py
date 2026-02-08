"""
通道基类 - 统一的通道抽象接口
"""
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from loguru import logger

class ChannelType(str, Enum):
    """通道类型"""
    WEB = "web"              # Web前端
    DINGTALK = "dingtalk"    # 钉钉
    FEISHU = "feishu"        # 飞书
    WECOM = "wecom"          # 企业微信
    WECHAT = "wechat"        # 微信(测试用)
    QQ = "qq"                # QQ(测试用)
    API = "api"              # REST API
    WEBHOOK = "webhook"      # Webhook
    

class MessageType(str, Enum):
    """消息类型"""
    TEXT = "text"
    MARKDOWN = "markdown"
    CARD = "card"            # 交互卡片
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    LINK = "link"
    

class Message(BaseModel):
    """统一消息模型"""
    message_id: str
    channel: ChannelType
    message_type: MessageType = MessageType.TEXT
    
    # 发送者信息
    sender_id: str
    sender_name: Optional[str] = None
    
    # 接收者信息
    receiver_id: str           # 用户ID或群组ID
    receiver_type: str = "user"  # user, group, channel
    
    # 消息内容
    content: str
    raw_content: Optional[Dict[str, Any]] = None  # 原始消息格式
    
    # 元数据
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # 引用/回复
    reply_to: Optional[str] = None
    thread_id: Optional[str] = None


class ChannelConfig(BaseModel):
    """通道配置"""
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    api_endpoint: Optional[str] = None
    token: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class BaseChannel(ABC):
    """通道基类"""
    
    def __init__(self, channel_name: str, channel_type: ChannelType, config: ChannelConfig):
        self.channel_name = channel_name
        self.channel_type = channel_type
        self.config = config
        self.is_connected = False
        self.is_running = False
        
        # 兼容：历史代码里大量使用 self.logger
        self.logger = logger.bind(channel=self.channel_name)

        # 消息处理回调
        self._on_message_callbacks: List[Callable] = []
        self._on_event_callbacks: List[Callable] = []
        
    # ============ 抽象方法 ============
    
    @abstractmethod
    async def connect(self) -> bool:
        """连接到通道"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开通道连接"""
        pass
    
    @abstractmethod
    async def send_message(
        self,
        receiver_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        """发送消息"""
        pass
    
    @abstractmethod
    async def send_card(
        self,
        receiver_id: str,
        card_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """发送交互卡片"""
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        pass
    
    # ============ 通用方法 ============
    
    async def start(self) -> bool:
        """启动通道"""
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
        """停止通道"""
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
        """注册消息回调"""
        if callback not in self._on_message_callbacks:
            self._on_message_callbacks.append(callback)
    
    def on_event(self, callback: Callable):
        """注册事件回调"""
        if callback not in self._on_event_callbacks:
            self._on_event_callbacks.append(callback)
    
    async def _emit_message(self, message: Message):
        """触发消息事件"""
        for callback in self._on_message_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")
    
    async def _emit_event(self, event_type: str, event_data: Dict[str, Any]):
        """触发通用事件"""
        for callback in self._on_event_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event_type, event_data)
                else:
                    callback(event_type, event_data)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """获取通道状态"""
        return {
            "channel_name": self.channel_name,
            "channel_type": self.channel_type,
            "is_connected": self.is_connected,
            "is_running": self.is_running,
            "enabled": self.config.enabled,
        }
    
    async def validate_config(self) -> bool:
        """验证配置"""
        if not self.config.enabled:
            return True
        return True  # 子类可以覆盖
