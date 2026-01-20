"""
热层管理器
负责将 LLM 提取的结构化信息存入 Neo4j
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from .llm_extractor import LLMExtractor
from .neo4j_connector import Neo4jConnector
from .models import (
    ExtractionResult, FactTuple, Neo4jNode, Neo4jRelation,
    NodeType, RelationType
)

logger = logging.getLogger(__name__)


class HotLayerManager:
    """热层记忆管理器"""
    
    def __init__(self, extractor: LLMExtractor, connector: Neo4jConnector, session_id: str):
        """
        初始化热层管理器
        
        Args:
            extractor: LLM 提取器
            connector: Neo4j 连接器
            session_id: 会话 ID
        """
        self.extractor = extractor
        self.connector = connector
        self.session_id = session_id
        self._ensure_session_node()
        logger.info(f"热层管理器初始化完成，会话: {session_id}")
    
    def _ensure_session_node(self):
        """确保会话节点存在"""
        session_node = Neo4jNode(
            id=f"session_{self.session_id}",
            type=NodeType.SESSION,
            content=f"会话 {self.session_id}",
            layer=0,
            importance=1.0,
            properties={"session_id": self.session_id}
        )
        self.connector.create_node(session_node)
    
    def process_message(self, role: str, content: str, 
                       context: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        处理一条消息，提取信息并存入图数据库
        
        Args:
            role: 角色 (user/assistant)
            content: 消息内容
            context: 对话上下文
            
        Returns:
            处理结果统计
        """
        # 确保当前 session 节点存在（因为 adapter 可能会复用 manager 实例但修改 session_id）
        self._ensure_session_node()

        logger.info(f"开始处理消息: role={role}, length={len(content)}")
        
        # 1. 使用 LLM 提取结构化信息
        extraction_result = self.extractor.extract(role, content, context)
        
        # 2. 创建消息节点
        message_node = self._create_message_node(role, content, extraction_result)
        
        # 3. 存储提取的事实三元组
        stats = {
            "message_id": message_node.id,
            "facts_count": 0,
            "entities_count": 0,
            "time_nodes": 0,
            "location_nodes": 0
        }
        
        for fact_tuple in extraction_result.tuples:
            self._store_fact_tuple(fact_tuple, message_node.id)
            stats["facts_count"] += 1
        
        # 4. 存储实体节点
        for entity in extraction_result.entities:
            self._create_entity_node(entity, message_node.id)
            stats["entities_count"] += 1
        
        # 5. 存储时间节点
        for time_expr in extraction_result.time_expressions:
            self._create_time_node(time_expr, message_node.id)
            stats["time_nodes"] += 1
        
        # 6. 存储地点节点
        for location in extraction_result.locations:
            self._create_location_node(location, message_node.id)
            stats["location_nodes"] += 1
        
        logger.info(f"消息处理完成: {stats}")
        return stats
    
    def _create_message_node(self, role: str, content: str, 
                            extraction: ExtractionResult) -> Neo4jNode:
        """创建消息节点"""
        # 提取情绪信息（Neo4j 不支持嵌套字典，需要扁平化）
        emotion_data = extraction.metadata.get("emotion", {})
        emotion_primary = emotion_data.get("primary", "neutral") if isinstance(emotion_data, dict) else "neutral"
        emotion_intensity = emotion_data.get("intensity", 0.5) if isinstance(emotion_data, dict) else 0.5
        
        message_node = Neo4jNode(
            type=NodeType.MESSAGE,
            content=content,
            layer=0,  # 热层
            importance=0.7 if role == "user" else 0.6,
            properties={
                "role": role,
                "session_id": self.session_id,
                "emotion_primary": emotion_primary,
                "emotion_intensity": float(emotion_intensity),
                "intent": extraction.metadata.get("intent", "unknown"),
                "keywords": extraction.metadata.get("keywords", [])
            }
        )
        
        message_id = self.connector.create_node(message_node)
        message_node.id = message_id
        
        # 连接到会话节点
        session_relation = Neo4jRelation(
            type=RelationType.PART_OF_SESSION,
            source_id=message_id,
            target_id=f"session_{self.session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return message_node
    
    def _store_fact_tuple(self, fact: FactTuple, message_id: str):
        """存储事实三元组到图中"""
        # 创建或获取主语节点（检查是否已存在）
        subject_id = self.connector.find_node_by_content(NodeType.ENTITY, fact.subject)
        if not subject_id:
            subject_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=fact.subject,
                layer=0,
                importance=fact.confidence,
                properties={"entity_type": "subject"}
            )
            subject_id = self.connector.create_node(subject_node)
        
        # 创建或获取谓语节点（动作）
        action_id = self.connector.find_node_by_content(NodeType.ACTION, fact.predicate)
        if not action_id:
            action_node = Neo4jNode(
                type=NodeType.ACTION,
                content=fact.predicate,
                layer=0,
                importance=fact.confidence,
                properties={"action_type": "predicate"}
            )
            action_id = self.connector.create_node(action_node)
        
        # 创建或获取宾语节点
        object_id = self.connector.find_node_by_content(NodeType.ENTITY, fact.object_)
        if not object_id:
            object_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=fact.object_,
                layer=0,
                importance=fact.confidence,
                properties={"entity_type": "object"}
            )
            object_id = self.connector.create_node(object_node)
        
        # 创建关系：主语 -> 动作
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.SUBJECT_OF,
            source_id=subject_id,
            target_id=action_id,
            weight=fact.confidence,
            properties={"from_message": message_id}
        ))
        
        # 创建关系：动作 -> 宾语
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.OBJECT_OF,
            source_id=action_id,
            target_id=object_id,
            weight=fact.confidence,
            properties={"from_message": message_id}
        ))
        
        # 创建关系：消息 -> 动作
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=action_id,
            target_id=message_id,
            weight=1.0
        ))
        
        # 如果有时间信息
        if fact.time:
            time_id = self._create_time_node(fact.time, message_id)
            self.connector.create_relation(Neo4jRelation(
                type=RelationType.AT_TIME,
                source_id=action_id,
                target_id=time_id,
                weight=fact.confidence
            ))
        
        # 如果有地点信息
        if fact.location:
            location_id = self._create_location_node(fact.location, message_id)
            self.connector.create_relation(Neo4jRelation(
                type=RelationType.AT_LOCATION,
                source_id=action_id,
                target_id=location_id,
                weight=fact.confidence
            ))
    
    def _normalize_content(self, content: str) -> str:
        """
        内容标准化
        1. 去除首尾空格
        2. 统一转小写（针对英文）
        """
        if not content:
            return ""
        return content.strip().lower()

    def _create_entity_node(self, entity: str, message_id: str) -> str:
        """创建或获取实体节点"""
        # 标准化
        normalized_entity = self._normalize_content(entity)
        if not normalized_entity:
            return ""
            
        # 先查找是否已存在
        entity_id = self.connector.find_node_by_content(NodeType.ENTITY, normalized_entity)
        
        if not entity_id:
            # 不存在则创建
            entity_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=normalized_entity,
                layer=0,
                importance=0.6,
                properties={"entity_type": "general", "original_text": entity}
            )
            entity_id = self.connector.create_node(entity_node)
        
        # 连接到消息（即使节点已存在，也建立新的关系）
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=entity_id,
            target_id=message_id,
            weight=0.8
        ))
        
        return entity_id
    
    def _create_time_node(self, time_expr: str, message_id: str) -> str:
        """创建或获取时间节点"""
        # 标准化
        normalized_time = self._normalize_content(time_expr)
        if not normalized_time:
            return ""
            
        # 先查找是否已存在
        time_id = self.connector.find_node_by_content(NodeType.TIME, normalized_time)
        
        if not time_id:
            # 不存在则创建
            time_node = Neo4jNode(
                type=NodeType.TIME,
                content=normalized_time,
                layer=0,
                importance=0.5,
                properties={"time_expression": normalized_time, "original_text": time_expr}
            )
            time_id = self.connector.create_node(time_node)
        
        # 连接到消息
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=time_id,
            target_id=message_id,
            weight=0.7
        ))
        
        return time_id
    
    def _create_location_node(self, location: str, message_id: str) -> str:
        """创建或获取地点节点"""
        # 标准化
        normalized_location = self._normalize_content(location)
        if not normalized_location:
            return ""
            
        # 先查找是否已存在
        location_id = self.connector.find_node_by_content(NodeType.LOCATION, normalized_location)
        
        if not location_id:
            # 不存在则创建
            location_node = Neo4jNode(
                type=NodeType.LOCATION,
                content=normalized_location,
                layer=0,
                importance=0.6,
                properties={"location_name": normalized_location, "original_text": location}
            )
            location_id = self.connector.create_node(location_node)
        
        # 连接到消息
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=location_id,
            target_id=message_id,
            weight=0.7
        ))
        
        return location_id
    
    def get_session_graph(self) -> Dict[str, Any]:
        """获取当前会话的图结构"""
        query = """
        MATCH (s:Session {id: $session_id})
        OPTIONAL MATCH (s)<-[:PART_OF_SESSION]-(m:Message)
        OPTIONAL MATCH (m)<-[:FROM_MESSAGE]-(entity)
        RETURN s, collect(DISTINCT m) as messages, collect(DISTINCT entity) as entities
        """
        
        results = self.connector.query(query, {"session_id": f"session_{self.session_id}"})
        
        if results:
            return {
                "session": results[0]["s"],
                "messages": results[0]["messages"],
                "entities": results[0]["entities"]
            }
        return {}
    
    def search_by_entity(self, entity_name: str) -> List[Dict[str, Any]]:
        """根据实体搜索相关消息"""
        query = """
        MATCH (e:Entity {content: $entity})
        MATCH (e)-[:FROM_MESSAGE]->(m:Message)
        RETURN m, e
        ORDER BY m.created_at DESC
        LIMIT 10
        """
        
        return self.connector.query(query, {"entity": entity_name})


