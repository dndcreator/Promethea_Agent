"""
Neo4j 分层记忆系统

三层架构：
- 热层（Hot Layer）：LLM 结构化信息提取（主谓宾+时间+地点+情绪）
- 温层（Warm Layer）：Embedding + 聚类的主题节点
- 冷层（Cold Layer）：LLM 摘要压缩的长期记忆
"""

from .hot_layer import HotLayerManager
from .warm_layer import WarmLayerManager, create_warm_layer_manager
from .cold_layer import ColdLayerManager, create_cold_layer_manager
from .llm_extractor import LLMExtractor, create_extractor_from_config
from .neo4j_connector import Neo4jConnector, Neo4jConnectionPool
from .adapter import MemoryAdapter, get_memory_adapter
from .auto_recall import AutoRecallEngine
from .forgetting import ForgettingManager, create_forgetting_manager
from .models import (
    FactTuple, 
    NodeType, 
    RelationType,
    ExtractionResult,
    Neo4jNode,
    Neo4jRelation
)

# 工厂函数：简化创建流程
def create_hot_layer_manager(session_id: str):
    """
    创建热层管理器（使用主配置）
    
    Args:
        session_id: 会话ID
        
    Returns:
        HotLayerManager 实例，失败返回 None
    """
    try:
        from config import load_config
        import logging
        
        logger = logging.getLogger(__name__)
        config = load_config()
        
        # 检查是否启用
        if not config.memory.enabled or not config.memory.neo4j.enabled:
            logger.info("记忆系统未启用（配置中 memory.enabled 或 neo4j.enabled 为 false）")
            return None
        
        # 创建提取器
        extractor = create_extractor_from_config(config)
        
        # 创建连接器（使用主配置的 Neo4j 配置）
        connector = Neo4jConnector(config.memory.neo4j)
        
        # 创建热层管理器
        return HotLayerManager(extractor, connector, session_id)
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"记忆系统初始化失败: {e}")
        return None


__all__ = [
    # 适配器（推荐使用）
    'MemoryAdapter',
    'get_memory_adapter',
    
    # 热层
    'HotLayerManager',
    'create_hot_layer_manager',
    
    # 温层
    'WarmLayerManager',
    'create_warm_layer_manager',
    
    # 冷层
    'ColdLayerManager',
    'create_cold_layer_manager',
    
    # 遗忘机制
    'ForgettingManager',
    'create_forgetting_manager',
    
    # 召回引擎
    'AutoRecallEngine',
    
    # 提取器
    'LLMExtractor',
    'create_extractor_from_config',
    
    # Neo4j
    'Neo4jConnector',
    'Neo4jConnectionPool',
    
    # 模型
    'FactTuple',
    'NodeType',
    'RelationType',
    'ExtractionResult',
    'Neo4jNode',
    'Neo4jRelation',
]

