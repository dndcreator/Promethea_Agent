"""Automatic memory recall engine."""

from typing import List, Dict
from datetime import datetime
from .neo4j_connector import Neo4jConnector
from .llm_extractor import LLMExtractor
from .session_scope import user_node_id
import logging

logger = logging.getLogger(__name__)


class AutoRecallEngine:
    """Heuristic-based automatic memory recall engine."""
    
    def __init__(self, connector: Neo4jConnector, extractor: LLMExtractor):
        self.connector = connector
        self.extractor = extractor
    
    def recall(self, query: str, session_id: str, user_id: str = "default_user") -> str:
        """Recall relevant memories and format them as context."""
        try:
            extraction = self.extractor.extract(role="user", content=query)
            entities = extraction.entities if extraction.entities else []
            
            params = self._calculate_params(query, entities)
            
            results = self._three_layer_query(entities, session_id, user_id, params['recent_days'])
            
            return self._format_context(results, params['max_tokens'], params['items_per_layer'])
            
        except Exception as e:
            logger.error(f"Memory auto-recall failed: {e}")
            return ""
    
    def _calculate_params(self, query: str, entities: List[str]) -> Dict:
        """Adaptively calculate recall parameters based on query and entities."""
        entity_count = len(entities)
        query_length = len(query)
        
        # Simple level heuristic.
        if entity_count >= 3 or query_length > 80:
            level = 'complex'
        elif entity_count >= 1 or query_length > 20:
            level = 'normal'
        else:
            level = 'simple'
        
        # Parameter presets.
        presets = {
            'simple':  {'max_tokens': 800,  'items_per_layer': 2, 'recent_days': 3},
            'normal':  {'max_tokens': 1500, 'items_per_layer': 3, 'recent_days': 7},
            'complex': {'max_tokens': 2500, 'items_per_layer': 5, 'recent_days': 14}
        }
        
        params = presets[level]

        # TODO: support localized temporal keywords if needed.
        # Currently we do not special-case Chinese phrases to avoid encoding issues.
        
        return params
    
    def _three_layer_query(self, entities: List[str], session_id: str, user_id: str, recent_days: int = 7) -> Dict:
        """Three-layer Cypher query (supports cross-session, user-scoped recall)."""
        
        # Important: query must match current graph schema.
        # - User node id uses "user_{user_id}"
        # - Session node id uses "session_{session_id}"
        # - Session belongs to User: (:Session)-[:OWNED_BY]->(:User)
        # - Message belongs to Session: (:Message)-[:PART_OF_SESSION]->(:Session)
        
        cypher = """
        // Find user node
        WITH $entities AS query_entities, $user_node_id AS uid, $session_node_id as current_sid
        
        // Layer 1: Direct entity matches (cross-session, but limited to this user)
        // Path: Entity -> Message -> Session -> User
        OPTIONAL MATCH (u:User {id: uid})
        OPTIONAL MATCH (e:Entity)
        WHERE e.content IN query_entities
        OPTIONAL MATCH (e)-[:FROM_MESSAGE]->(direct_msg:Message)-[:PART_OF_SESSION]->(s:Session)-[:OWNED_BY]->(u)
        WITH collect(DISTINCT {
            content: direct_msg.content,
            time: direct_msg.created_at,
            importance: direct_msg.importance,
            layer: 'direct',
            session_id: s.session_id
        }) AS layer1_results, uid, current_sid

        // Layer 2: Indirect matches via Action graph
        OPTIONAL MATCH (u:User {id: uid})
        OPTIONAL MATCH (e0:Entity)
        WHERE e0.content IN $entities
        OPTIONAL MATCH (e0)-[:SUBJECT_OF|OBJECT_OF]-(a:Action)-[:SUBJECT_OF|OBJECT_OF]-(related:Entity)
        WHERE related.content IS NOT NULL AND related.content <> e0.content
        OPTIONAL MATCH (related)-[:FROM_MESSAGE]->(related_msg:Message)-[:PART_OF_SESSION]->(s:Session)-[:OWNED_BY]->(u)
        WITH layer1_results, collect(DISTINCT {
            content: related_msg.content,
            time: related_msg.created_at,
            importance: related_msg.importance,
            layer: 'related',
            via: related.content,
            session_id: s.session_id
        }) AS layer2_results, uid, current_sid

        // Layer 3: Recent context window (current session only, preserve recency)
        OPTIONAL MATCH (s:Session {id: current_sid})
        OPTIONAL MATCH (recent_msg:Message)-[:PART_OF_SESSION]->(s)
        WHERE recent_msg.created_at > datetime() - duration({days: $recent_days})
        WITH layer1_results, layer2_results, collect(DISTINCT {
            content: recent_msg.content,
            time: recent_msg.created_at,
            importance: recent_msg.importance,
            layer: 'recent'
        }) AS layer3_results

        RETURN {
            direct: [r IN layer1_results WHERE r.content IS NOT NULL],
            related: [r IN layer2_results WHERE r.content IS NOT NULL],
            recent: [r IN layer3_results WHERE r.content IS NOT NULL]
        } AS results
        """
        
        try:
            result = self.connector.query(
                cypher,
                parameters={
                    "entities": entities if entities else [""],
                    "user_node_id": user_node_id(user_id),
                    "session_node_id": f"session_{session_id}",
                    "recent_days": recent_days
                }
            )
            
            return result[0]['results'] if result else {
                'direct': [], 'related': [], 'recent': []
            }
        except Exception as e:
            logger.error(f"Auto-recall Cypher query failed: {e}")
            return {'direct': [], 'related': [], 'recent': []}
    
    def _format_context(self, results: Dict, max_tokens: int = 1500, items_per_layer: int = 3) -> str:
        """Format recalled results into a compact context string."""
        lines = []
        token_count = 0
        
        # Process in order of priority.
        priorities = [
            ('direct', results.get('direct', []), '[Direct memories]'),
            ('related', results.get('related', []), '[Related knowledge]'),
            ('recent', results.get('recent', []), '[Recent dialog]')
        ]
        
        for layer_name, items, header in priorities:
            if not items:
                continue
            
            sorted_items = sorted(
                items,
                key=lambda x: (x.get('importance', 0), x.get('time', datetime.min)),
                reverse=True
            )
            
            layer_lines = [header]
            for item in sorted_items[:items_per_layer]:
                content = item.get('content', '')
                if not content:
                    continue
                
                # Rough token limit.
                est_tokens = len(content) // 1.5
                if token_count + est_tokens > max_tokens:
                    break
                
                # Format timestamp.
                t = item.get('time')
                # Neo4j driver may return neo4j.time.DateTime; do a best-effort conversion.
                if t is None:
                    time_str = ''
                elif hasattr(t, "to_native"):
                    try:
                        time_str = t.to_native().strftime('%m-%d')
                    except Exception:
                        time_str = str(t)[:10]
                elif hasattr(t, "strftime"):
                    time_str = t.strftime('%m-%d')
                else:
                    time_str = str(t)[:10]
                
                via_str = f" (via: {item['via']})" if item.get('via') else ""
                # If this is conversation memory, we could also label its session (optional):
                # session_str = f" [Session: {item.get('session_id')}]" if item.get('session_id') else ""
                
                layer_lines.append(f"- [{time_str}] {content[:100]}...{via_str}")
                token_count += est_tokens
            
            if len(layer_lines) > 1:
                lines.extend(layer_lines)
                lines.append("")
        
        return "\n".join(lines) if lines else ""
