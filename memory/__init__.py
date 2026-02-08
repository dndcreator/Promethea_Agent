"""
宸ュ巶鍑芥暟锛岀敤浜庡垱寤鸿蹇嗙郴缁熷悇灞傜鐞嗗櫒
"""
from typing import Optional
from .neo4j_connector import Neo4jConnectionPool
from .llm_extractor import LLMExtractor
from .hot_layer import HotLayerManager
from .warm_layer import WarmLayerManager
from .cold_layer import ColdLayerManager
from .forgetting import ForgettingManager
from config import load_config

def create_hot_layer_manager(session_id: str, user_id: str = "default_user") -> Optional[HotLayerManager]:
    """鍒涘缓鐑眰绠＄悊鍣?""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    connector = Neo4jConnectionPool.get_connector(config.memory.neo4j)
    if not connector:
        return None
        
    extractor = LLMExtractor(config.api)
    return HotLayerManager(extractor, connector, session_id, user_id)

def create_warm_layer_manager(connector) -> Optional[WarmLayerManager]:
    """鍒涘缓娓╁眰绠＄悊鍣?""
    config = load_config()
    if not config.memory.enabled or not config.memory.warm_layer.enabled:
        return None
        
    return WarmLayerManager(connector, config)

def create_cold_layer_manager(connector) -> Optional[ColdLayerManager]:
    """鍒涘缓鍐峰眰绠＄悊鍣?""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    return ColdLayerManager(connector, config)

def create_forgetting_manager(connector) -> Optional[ForgettingManager]:
    """鍒涘缓閬楀繕绠＄悊鍣?""
    config = load_config()
    if not config.memory.enabled:
        return None
        
    return ForgettingManager(connector)

