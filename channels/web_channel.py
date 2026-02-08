"""
Web通道 - 保留现有Web前端功能
"""
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from .base import BaseChannel, ChannelType, MessageType, Message, ChannelConfig


class WebChannel(BaseChannel):
    """Web通道实现"""
    
    def __init__(self, config: ChannelConfig):
        super().__init__("web", ChannelType.WEB, config)
        
        # Web通道使用WebSocket，连接由gateway管理
        self.websocket_connections: Dict[str, Any] = {}
    
    async def connect(self) -> bool:
        """连接（Web通道总是可用的）"""
        self.is_connected = True
        self.logger.info("Web channel connected")
        return True
    
    async def disconnect(self) -> bool:
        """断开连接"""
        self.is_connected = False
        self.websocket_connections.clear()
        self.logger.info("Web channel disconnected")
        return True
    
    async def send_message(
        self,
        receiver_id: str,  # connection_id
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        """发送消息到Web客户端"""
        try:
            message_id = f"web_msg_{uuid.uuid4().hex[:8]}"
            
            # 通过gateway发送（实际发送逻辑在gateway中）
            result = {
                "success": True,
                "message_id": message_id,
                "channel": "web",
                "receiver_id": receiver_id,
                "timestamp": datetime.now().isoformat()
            }
            
            self.logger.debug(f"Sent message to web client {receiver_id}: {message_id}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error sending web message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_card(
        self,
        receiver_id: str,
        card_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """发送交互卡片（Web使用HTML渲染）"""
        # Web通道使用HTML/JSON格式
        return await self.send_message(
            receiver_id,
            str(card_data),
            MessageType.CARD,
            **kwargs
        )
    
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户信息（Web通道使用connection_id）"""
        return {
            "user_id": user_id,
            "channel": "web",
            "user_type": "web_client"
        }
    
    def register_websocket(self, connection_id: str, websocket: Any):
        """注册WebSocket连接"""
        self.websocket_connections[connection_id] = websocket
        self.logger.debug(f"Registered websocket for connection: {connection_id}")
    
    def unregister_websocket(self, connection_id: str):
        """注销WebSocket连接"""
        if connection_id in self.websocket_connections:
            del self.websocket_connections[connection_id]
            self.logger.debug(f"Unregistered websocket for connection: {connection_id}")
