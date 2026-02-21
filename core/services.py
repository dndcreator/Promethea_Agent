"""
"""
from typing import Optional, Any
from loguru import logger

from .plugins.runtime import get_active_plugin_registry
from .plugins.registry import find_service


def get_memory_service() -> Optional[Any]:
    """
    
    Returns:
    """
    try:
        service = find_service("memory")
        if service:
            return service
        
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
    
    Args:
        
    Returns:
    """
    try:
        from .plugins.registry import find_channel
        return find_channel(channel_id)
    except Exception as e:
        logger.error(f"Error getting channel service {channel_id}: {e}")
        return None


def ensure_plugin_system_loaded():
    """
    
    Returns:
    """
    registry = get_active_plugin_registry()
    if registry is None:
        logger.warning("Plugin system not loaded yet")
        return False
    return True
