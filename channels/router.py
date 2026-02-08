"""
消息路由器 - 统一的消息分发和路由
"""
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, List
from .base import BaseChannel, Message, MessageType, ChannelType
from .registry import ChannelRegistry

logger = logging.getLogger("Channels.Router")


class MessageRouter:
    """消息路由器"""
    
    def __init__(self, channel_registry: ChannelRegistry):
        self.registry = channel_registry
        
        # 路由规则: channel_name -> handler
        self._route_handlers: Dict[str, Callable] = {}
        
        # 全局消息处理器
        self._global_handlers: List[Callable] = []
        
        # 消息过滤器
        self._filters: List[Callable] = []
        
    def register_route(self, channel_name: str, handler: Callable):
        """注册路由处理器"""
        self._route_handlers[channel_name] = handler
        logger.info(f"Registered route handler for channel: {channel_name}")
    
    def register_global_handler(self, handler: Callable):
        """注册全局处理器"""
        if handler not in self._global_handlers:
            self._global_handlers.append(handler)
            logger.info("Registered global message handler")
    
    def add_filter(self, filter_func: Callable):
        """添加消息过滤器"""
        if filter_func not in self._filters:
            self._filters.append(filter_func)
            logger.info("Added message filter")
    
    async def route_message(self, message: Message) -> Any:
        """路由消息到处理器"""
        try:
            # 应用过滤器
            for filter_func in self._filters:
                if asyncio.iscoroutinefunction(filter_func):
                    should_continue = await filter_func(message)
                else:
                    should_continue = filter_func(message)
                
                if not should_continue:
                    logger.debug(f"Message filtered out: {message.message_id}")
                    return None
            
            # 查找通道特定处理器
            channel = self.registry.get(message.channel.value)
            if not channel:
                logger.warning(f"Channel not found for message: {message.channel}")
                return None
            
            handler = self._route_handlers.get(message.channel.value)
            
            # 执行处理器
            result = None
            if handler:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
            
            # 执行全局处理器
            for global_handler in self._global_handlers:
                try:
                    if asyncio.iscoroutinefunction(global_handler):
                        await global_handler(message)
                    else:
                        global_handler(message)
                except Exception as e:
                    logger.error(f"Error in global handler: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error routing message: {e}")
            return None
    
    async def send_message(
        self,
        channel_name: str,
        receiver_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """通过路由器发送消息"""
        channel = self.registry.get(channel_name)
        if not channel:
            logger.error(f"Channel not found: {channel_name}")
            return None
        
        if not channel.is_connected:
            logger.error(f"Channel not connected: {channel_name}")
            return None
        
        try:
            result = await channel.send_message(
                receiver_id,
                content,
                message_type,
                **kwargs
            )
            return result
        except Exception as e:
            logger.error(f"Error sending message via {channel_name}: {e}")
            return None
    
    async def broadcast(
        self,
        content: str,
        channel_types: Optional[List[ChannelType]] = None,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        """广播消息到多个通道"""
        results = {}
        
        # 确定要广播的通道
        channels_to_broadcast = []
        if channel_types:
            for channel_type in channel_types:
                channels_to_broadcast.extend(self.registry.get_by_type(channel_type))
        else:
            channels_to_broadcast = list(self.registry.get_all().values())
        
        # 发送消息
        for channel in channels_to_broadcast:
            if not channel.is_connected:
                continue
            
            try:
                # 这里需要目标ID，实际使用时需要从配置获取默认接收者
                # 暂时跳过
                pass
            except Exception as e:
                logger.error(f"Error broadcasting to {channel.channel_name}: {e}")
                results[channel.channel_name] = {"success": False, "error": str(e)}
        
        return results
    
    def setup_channel_listeners(self):
        """设置通道监听器"""
        for channel in self.registry.get_all().values():
            # 注册消息回调
            channel.on_message(self.route_message)
            logger.info(f"Set up listener for channel: {channel.channel_name}")
