"""
"""
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, List
from .base import BaseChannel, Message, MessageType, ChannelType
from .registry import ChannelRegistry

logger = logging.getLogger("Channels.Router")


class MessageRouter:
    """TODO: add docstring."""
    
    def __init__(self, channel_registry: ChannelRegistry):
        self.registry = channel_registry
        
        self._route_handlers: Dict[str, Callable] = {}
        
        self._global_handlers: List[Callable] = []
        
        self._filters: List[Callable] = []
        
    def register_route(self, channel_name: str, handler: Callable):
        self._route_handlers[channel_name] = handler
        logger.info(f"Registered route handler for channel: {channel_name}")
    
    def register_global_handler(self, handler: Callable):
        """TODO: add docstring."""
        if handler not in self._global_handlers:
            self._global_handlers.append(handler)
            logger.info("Registered global message handler")
    
    def add_filter(self, filter_func: Callable):
        if filter_func not in self._filters:
            self._filters.append(filter_func)
            logger.info("Added message filter")
    
    async def route_message(self, message: Message) -> Any:
        """TODO: add docstring."""
        try:
            for filter_func in self._filters:
                if asyncio.iscoroutinefunction(filter_func):
                    should_continue = await filter_func(message)
                else:
                    should_continue = filter_func(message)
                
                if not should_continue:
                    logger.debug(f"Message filtered out: {message.message_id}")
                    return None
            
            channel = self.registry.get(message.channel.value)
            if not channel:
                logger.warning(f"Channel not found for message: {message.channel}")
                return None
            
            handler = self._route_handlers.get(message.channel.value)
            
            result = None
            if handler:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(message)
                else:
                    result = handler(message)
            
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
        """TODO: add docstring."""
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
        results = {}
        
        channels_to_broadcast = []
        if channel_types:
            for channel_type in channel_types:
                channels_to_broadcast.extend(self.registry.get_by_type(channel_type))
        else:
            channels_to_broadcast = list(self.registry.get_all().values())
        
        # Deduplicate channels when multiple channel types overlap.
        unique_channels = {}
        for channel in channels_to_broadcast:
            unique_channels[channel.channel_name] = channel

        receiver_map = kwargs.get("receiver_map") or {}
        default_receiver_id = kwargs.get("receiver_id") or kwargs.get("default_receiver_id")
        channel_kwargs = dict(kwargs)
        channel_kwargs.pop("receiver_map", None)
        channel_kwargs.pop("default_receiver_id", None)
        channel_kwargs.pop("receiver_id", None)

        for channel in unique_channels.values():
            if not channel.is_connected:
                continue
            
            try:
                receiver_id = receiver_map.get(channel.channel_name, default_receiver_id)
                if receiver_id is None:
                    results[channel.channel_name] = {
                        "success": False,
                        "error": "missing receiver_id for broadcast target",
                    }
                    continue

                result = await channel.send_message(
                    receiver_id=receiver_id,
                    content=content,
                    message_type=message_type,
                    **channel_kwargs,
                )
                results[channel.channel_name] = result
            except Exception as e:
                logger.error(f"Error broadcasting to {channel.channel_name}: {e}")
                results[channel.channel_name] = {"success": False, "error": str(e)}
        
        return results
    
    def setup_channel_listeners(self):
        for channel in self.registry.get_all().values():
            channel.on_message(self.route_message)
            logger.info(f"Set up listener for channel: {channel.channel_name}")
