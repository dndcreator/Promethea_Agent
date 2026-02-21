"""
Factory helpers for creating memory system managers (hot / warm / cold / forgetting).

These helpers read the global config and return `None` when the corresponding
layer is disabled, so callers can simply check for a falsy value.
"""
from typing import Optional
from .neo4j_connector import Neo4jConnectionPool
from .llm_extractor import create_extractor_from_config
from .hot_layer import HotLayerManager
from .warm_layer import WarmLayerManager
from .cold_layer import ColdLayerManager
from .forgetting import ForgettingManager
from config import load_config

def create_hot_layer_manager(session_id: str, user_id: str = "default_user") -> Optional[HotLayerManager]:
    """Create hot-layer manager for a given session/user."""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    connector = Neo4jConnectionPool.get_connector(config.memory.neo4j)
    if not connector:
        return None
        
    extractor = create_extractor_from_config(config)
    return HotLayerManager(extractor, connector, session_id, user_id)

def create_warm_layer_manager(connector) -> Optional[WarmLayerManager]:
    """Create warm-layer manager (clustering / embeddings)."""
    config = load_config()
    if not config.memory.enabled or not config.memory.warm_layer.enabled:
        return None
        
    return WarmLayerManager(connector, config)

def create_cold_layer_manager(connector) -> Optional[ColdLayerManager]:
    """Create cold-layer manager (long-term summaries)."""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    return ColdLayerManager(connector, config)

def create_forgetting_manager(connector) -> Optional[ForgettingManager]:
    """Create forgetting manager (time decay / cleanup)."""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    return ForgettingManager(connector)

