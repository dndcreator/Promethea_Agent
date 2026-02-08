"""
统一的服务获取接口 - 通过插件注册表获取服务
避免直接 import，实现真正的解耦
"""
from typing import Optional, Any
from loguru import logger

from .plugins.runtime import get_active_plugin_registry
from .plugins.registry import find_service


def get_memory_service() -> Optional[Any]:
    """
    通过插件注册表获取记忆服务
    
    Returns:
        MemoryAdapter 实例，如果未加载则返回 None
    """
    try:
        service = find_service("memory")
        if service:
            return service
        
        # 如果插件系统未加载，回退到直接 import（向后兼容）
        logger.warning("Memory service not found in plugin registry, falling back to direct import")
        try:
            from memory.adapter import get_memory_adapter
            return get_memory_adapter()
        except ImportError:
            return None
    except Exception as e:
        logger.error(f"Error getting memory service: {e}")
        return None


def get_channel_service(channel_id: str) -> Optional[Any]:
    """
    通过插件注册表获取通道服务
    
    Args:
        channel_id: 通道ID (如 "web", "dingtalk")
        
    Returns:
        Channel 实例，如果未找到则返回 None
    """
    try:
        from .plugins.registry import find_channel
        return find_channel(channel_id)
    except Exception as e:
        logger.error(f"Error getting channel service {channel_id}: {e}")
        return None


def ensure_plugin_system_loaded():
    """
    确保插件系统已加载（用于启动时检查）
    
    Returns:
        bool: 插件系统是否已加载
    """
    registry = get_active_plugin_registry()
    if registry is None:
        logger.warning("Plugin system not loaded yet")
        return False
    return True
