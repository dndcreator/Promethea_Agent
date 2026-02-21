"""
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
from .session_scope import user_node_id

logger = logging.getLogger(__name__)


class HotLayerManager:
    """TODO: add docstring."""
    
    def __init__(self, extractor: LLMExtractor, connector: Neo4jConnector, session_id: str, user_id: str = "default_user"):
        """
        Initialize hot-layer manager and ensure user/session nodes exist.
        
        Args:
            extractor: LLM extractor instance.
            connector: Neo4j connector instance.
            session_id: Session ID.
            user_id: User ID (default: default_user).
        """
        self.extractor = extractor
        self.connector = connector
        self.session_id = session_id
        self.user_id = user_id
        self._ensure_session_node()
    
    def _ensure_session_node(self):
        uid = user_node_id(self.user_id)
        user_node = Neo4jNode(
            id=uid,
            type=NodeType.USER,
            content=f"User {self.user_id}",
            layer=0,
            importance=1.0,
            properties={"user_id": self.user_id}
        )
        self.connector.create_node(user_node)

        session_node = Neo4jNode(
            id=f"session_{self.session_id}",
            type=NodeType.SESSION,
            content=f"Session {self.session_id}",
            layer=0,
            importance=1.0,
            properties={"session_id": self.session_id}
        )
        self.connector.create_node(session_node)

        relation = Neo4jRelation(
            type=RelationType.OWNED_BY,
            source_id=f"session_{self.session_id}",
            target_id=uid,
            weight=1.0
        )
        self.connector.create_relation(relation)
    
    def process_message(
        self,
        role: str,
        content: str,
        context: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        
        Args:
            
        Returns:
        """
        self._ensure_session_node()

        logger.info("Processing memory write candidate: role=%s session=%s", role, self.session_id)
        
        extraction_result = self.extractor.extract(role, content, context)
        
        message_node = self._create_message_node(role, content, extraction_result, metadata=metadata)
        
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
        
        for entity in extraction_result.entities:
            self._create_entity_node(entity, message_node.id)
            stats["entities_count"] += 1
        
        for time_expr in extraction_result.time_expressions:
            self._create_time_node(time_expr, message_node.id)
            stats["time_nodes"] += 1
        
        for location in extraction_result.locations:
            self._create_location_node(location, message_node.id)
            stats["location_nodes"] += 1
        
        logger.info(
            "Memory write completed: session=%s message_id=%s facts=%s entities=%s",
            self.session_id,
            message_node.id,
            stats["facts_count"],
            stats["entities_count"],
        )
        return stats
    
    def _create_message_node(
        self,
        role: str,
        content: str,
        extraction: ExtractionResult,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Neo4jNode:
        """TODO: add docstring."""
        emotion_data = extraction.metadata.get("emotion", {})
        emotion_primary = emotion_data.get("primary", "neutral") if isinstance(emotion_data, dict) else "neutral"
        emotion_intensity = emotion_data.get("intensity", 0.5) if isinstance(emotion_data, dict) else 0.5
        
        metadata = metadata or {}
        message_node = Neo4jNode(
            type=NodeType.MESSAGE,
            content=content,
            layer=0,
            importance=0.7 if role == "user" else 0.6,
            properties={
                "role": role,
                "session_id": self.session_id,
                "user_id": self.user_id, # user_id for strict user isolation
                "emotion_primary": emotion_primary,
                "emotion_intensity": float(emotion_intensity),
                "intent": extraction.metadata.get("intent", "unknown"),
                "keywords": extraction.metadata.get("keywords", []),
                "memory_type": metadata.get("memory_type"),
                "memory_source": metadata.get("memory_source"),
                "semantic_keys": metadata.get("semantic_keys", []),
            }
        )
        
        message_id = self.connector.create_node(message_node)
        message_node.id = message_id
        
        session_relation = Neo4jRelation(
            type=RelationType.PART_OF_SESSION,
            source_id=message_id,
            target_id=f"session_{self.session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return message_node
    
    def _store_fact_tuple(self, fact: FactTuple, message_id: str):
        """TODO: add docstring."""
        edge_suffix = message_id
            NodeType.ENTITY, fact.subject, user_id=self.user_id
        )
        if not subject_id:
            subject_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=fact.subject,
                layer=0,
                importance=fact.confidence,
                properties={"entity_type": "subject"}
            )
            subject_id = self.connector.create_node(subject_node)
        
            NodeType.ACTION, fact.predicate, user_id=self.user_id
        )
        if not action_id:
            action_node = Neo4jNode(
                type=NodeType.ACTION,
                content=fact.predicate,
                layer=0,
                importance=fact.confidence,
                properties={"action_type": "predicate"}
            )
            action_id = self.connector.create_node(action_node)
        
            NodeType.ENTITY, fact.object_, user_id=self.user_id
        )
        if not object_id:
            object_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=fact.object_,
                layer=0,
                importance=fact.confidence,
                properties={"entity_type": "object"}
            )
            object_id = self.connector.create_node(object_node)
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.SUBJECT_OF,
            source_id=subject_id,
            target_id=action_id,
            edge_key=f"subject_of:{subject_id}:{action_id}:{edge_suffix}",
            weight=fact.confidence,
            properties={"from_message": message_id}
        ))
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.OBJECT_OF,
            source_id=action_id,
            target_id=object_id,
            edge_key=f"object_of:{action_id}:{object_id}:{edge_suffix}",
            weight=fact.confidence,
            properties={"from_message": message_id}
        ))
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=action_id,
            target_id=message_id,
            edge_key=f"from_message:{action_id}:{message_id}",
            weight=1.0
        ))
        
        if fact.time:
            time_id = self._create_time_node(fact.time, message_id)
            self.connector.create_relation(Neo4jRelation(
                type=RelationType.AT_TIME,
                source_id=action_id,
                target_id=time_id,
                edge_key=f"at_time:{action_id}:{time_id}:{edge_suffix}",
                weight=fact.confidence
            ))
        
        if fact.location:
            location_id = self._create_location_node(fact.location, message_id)
            self.connector.create_relation(Neo4jRelation(
                type=RelationType.AT_LOCATION,
                source_id=action_id,
                target_id=location_id,
                edge_key=f"at_location:{action_id}:{location_id}:{edge_suffix}",
                weight=fact.confidence
            ))
    
    def _normalize_content(self, content: str) -> str:
        """
        """
        if not content:
            return ""
        return content.strip().lower()

    def _create_entity_node(self, entity: str, message_id: str) -> str:
        """TODO: add docstring."""
        normalized_entity = self._normalize_content(entity)
        if not normalized_entity:
            return ""
            
        entity_id = self.connector.find_node_by_content(
            NodeType.ENTITY, normalized_entity, user_id=self.user_id
        )
        
        if not entity_id:
            entity_node = Neo4jNode(
                type=NodeType.ENTITY,
                content=normalized_entity,
                layer=0,
                importance=0.6,
                properties={"entity_type": "general", "original_text": entity}
            )
            entity_id = self.connector.create_node(entity_node)
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=entity_id,
            target_id=message_id,
            edge_key=f"from_message:{entity_id}:{message_id}",
            weight=0.8
        ))
        
        return entity_id
    
    def _create_time_node(self, time_expr: str, message_id: str) -> str:
        normalized_time = self._normalize_content(time_expr)
        if not normalized_time:
            return ""
            
        time_id = self.connector.find_node_by_content(
            NodeType.TIME, normalized_time, user_id=self.user_id
        )
        
        if not time_id:
            time_node = Neo4jNode(
                type=NodeType.TIME,
                content=normalized_time,
                layer=0,
                importance=0.5,
                properties={"time_expression": normalized_time, "original_text": time_expr}
            )
            time_id = self.connector.create_node(time_node)
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=time_id,
            target_id=message_id,
            edge_key=f"from_message:{time_id}:{message_id}",
            weight=0.7
        ))
        
        return time_id
    
    def _create_location_node(self, location: str, message_id: str) -> str:
        """TODO: add docstring."""
        normalized_location = self._normalize_content(location)
        if not normalized_location:
            return ""
            
        location_id = self.connector.find_node_by_content(
            NodeType.LOCATION, normalized_location, user_id=self.user_id
        )
        
        if not location_id:
            location_node = Neo4jNode(
                type=NodeType.LOCATION,
                content=normalized_location,
                layer=0,
                importance=0.6,
                properties={"location_name": normalized_location, "original_text": location}
            )
            location_id = self.connector.create_node(location_node)
        
        self.connector.create_relation(Neo4jRelation(
            type=RelationType.FROM_MESSAGE,
            source_id=location_id,
            target_id=message_id,
            edge_key=f"from_message:{location_id}:{message_id}",
            weight=0.7
        ))
        
        return location_id
    
    def get_session_graph(self) -> Dict[str, Any]:
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
        query = """
        MATCH (e:Entity {content: $entity})
        MATCH (e)-[:FROM_MESSAGE]->(m:Message)
        RETURN m, e
        ORDER BY m.created_at DESC
        LIMIT 10
        """
        
        return self.connector.query(query, {"entity": entity_name})
