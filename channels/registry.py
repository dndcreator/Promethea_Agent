"""
"""
from loguru import logger
from typing import Dict, Optional, List
from .base import BaseChannel, ChannelType


class ChannelRegistry:
    """TODO: add docstring."""
    
    def __init__(self):
        self._channels: Dict[str, BaseChannel] = {}
        self._channels_by_type: Dict[ChannelType, List[BaseChannel]] = {}
    
    def register(self, channel: BaseChannel) -> bool:
        try:
            channel_name = channel.channel_name
            
            if channel_name in self._channels:
                logger.warning(f"Channel {channel_name} already registered, replacing...")
            
            self._channels[channel_name] = channel
            
            channel_type = channel.channel_type
            if channel_type not in self._channels_by_type:
                self._channels_by_type[channel_type] = []
            
            if channel not in self._channels_by_type[channel_type]:
                self._channels_by_type[channel_type].append(channel)
            
            logger.info(f"Registered channel: {channel_name} ({channel_type})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register channel: {e}")
            return False
    
    def unregister(self, channel_name: str) -> bool:
        if channel_name not in self._channels:
            logger.warning(f"Channel {channel_name} not found")
            return False
        
        channel = self._channels[channel_name]
        channel_type = channel.channel_type
        
        del self._channels[channel_name]
        
        if channel_type in self._channels_by_type:
            if channel in self._channels_by_type[channel_type]:
                self._channels_by_type[channel_type].remove(channel)
        
        logger.info(f"Unregistered channel: {channel_name}")
        return True
    
    def get(self, channel_name: str) -> Optional[BaseChannel]:
        return self._channels.get(channel_name)
    
    def get_by_type(self, channel_type: ChannelType) -> List[BaseChannel]:
        return self._channels_by_type.get(channel_type, [])
    
    def get_all(self) -> Dict[str, BaseChannel]:
        return self._channels.copy()
    
    def list_channels(self) -> List[str]:
        return list(self._channels.keys())
    
    async def start_all(self) -> Dict[str, bool]:
        results = {}
        for name, channel in self._channels.items():
            try:
                success = await channel.start()
                results[name] = success
            except Exception as e:
                logger.error(f"Failed to start channel {name}: {e}")
                results[name] = False
        return results
    
    async def stop_all(self) -> Dict[str, bool]:
        results = {}
        for name, channel in self._channels.items():
            try:
                success = await channel.stop()
                results[name] = success
            except Exception as e:
                logger.error(f"Failed to stop channel {name}: {e}")
                results[name] = False
        return results
    
    def get_status_all(self) -> Dict[str, Dict]:
        return {
            name: channel.get_status()
            for name, channel in self._channels.items()
        }
