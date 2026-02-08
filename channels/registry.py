"""
通道注册表 - 管理所有通道实例
"""
from loguru import logger
from typing import Dict, Optional, List
from .base import BaseChannel, ChannelType


class ChannelRegistry:
    """通道注册表"""
    
    def __init__(self):
        self._channels: Dict[str, BaseChannel] = {}
        self._channels_by_type: Dict[ChannelType, List[BaseChannel]] = {}
    
    def register(self, channel: BaseChannel) -> bool:
        """注册通道"""
        try:
            channel_name = channel.channel_name
            
            if channel_name in self._channels:
                logger.warning(f"Channel {channel_name} already registered, replacing...")
            
            self._channels[channel_name] = channel
            
            # 按类型索引
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
        """注销通道"""
        if channel_name not in self._channels:
            logger.warning(f"Channel {channel_name} not found")
            return False
        
        channel = self._channels[channel_name]
        channel_type = channel.channel_type
        
        # 移除
        del self._channels[channel_name]
        
        if channel_type in self._channels_by_type:
            if channel in self._channels_by_type[channel_type]:
                self._channels_by_type[channel_type].remove(channel)
        
        logger.info(f"Unregistered channel: {channel_name}")
        return True
    
    def get(self, channel_name: str) -> Optional[BaseChannel]:
        """获取通道"""
        return self._channels.get(channel_name)
    
    def get_by_type(self, channel_type: ChannelType) -> List[BaseChannel]:
        """按类型获取通道"""
        return self._channels_by_type.get(channel_type, [])
    
    def get_all(self) -> Dict[str, BaseChannel]:
        """获取所有通道"""
        return self._channels.copy()
    
    def list_channels(self) -> List[str]:
        """列出所有通道名称"""
        return list(self._channels.keys())
    
    async def start_all(self) -> Dict[str, bool]:
        """启动所有通道"""
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
        """停止所有通道"""
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
        """获取所有通道状态"""
        return {
            name: channel.get_status()
            for name, channel in self._channels.items()
        }
