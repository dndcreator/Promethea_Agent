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
        """Recall query across all sessions of one user (excluding current session)."""
        
        # Important: query must match current graph schema.
        # - User node id uses "user_{user_id}"
        # - Session node id uses "session_{session_id}"
        # - Session belongs to User: (:Session)-[:OWNED_BY]->(:User)
        # - Message belongs to Session: (:Message)-[:PART_OF_SESSION]->(:Session)
        
        cypher = """
        WITH $entities AS query_entities, $user_node_id AS uid, $session_node_id AS current_sid
        OPTIONAL MATCH (u:User {id: uid})

        // Cold layer first: summaries across sessions
        OPTIONAL MATCH (sum:Summary)
        OPTIONAL MATCH (sum_s:Session)-[:OWNED_BY]->(u)
        WHERE EXISTS { MATCH (sum)-[rel]->(sum_s) WHERE type(rel) = 'SUMMARIZES' }
          AND sum_s.id <> current_sid
        WITH u, query_entities, current_sid, collect(DISTINCT {
            content: sum.content,
            time: sum.created_at,
            importance: sum.importance,
            layer: 'summary',
            session_id: sum_s.session_id
        }) AS summary_results

        // Warm layer next: concept nodes across sessions
        OPTIONAL MATCH (c:Concept)-[:PART_OF_SESSION]->(concept_s:Session)-[:OWNED_BY]->(u)
        WHERE concept_s.id <> current_sid
        WITH u, query_entities, current_sid, summary_results, collect(DISTINCT {
            content: c.content,
            time: c.created_at,
            importance: c.importance,
            layer: 'concept',
            session_id: concept_s.session_id
        }) AS concept_results

        // Layer 1: direct entity-hit memories (cross-session, user-scoped)
        OPTIONAL MATCH (e:Entity)
        WHERE size(query_entities) > 0 AND e.content IN query_entities
        OPTIONAL MATCH (e)-[:FROM_MESSAGE]->(direct_msg:Message)-[:PART_OF_SESSION]->(direct_s:Session)-[:OWNED_BY]->(u)
        WITH u, query_entities, current_sid, summary_results, concept_results, collect(DISTINCT {
            content: direct_msg.content,
            time: direct_msg.created_at,
            importance: direct_msg.importance,
            layer: 'direct',
            session_id: direct_s.session_id
        }) AS layer1_results

        // Layer 2: related memories via action/entity graph
        OPTIONAL MATCH (e0:Entity)
        WHERE size(query_entities) > 0 AND e0.content IN query_entities
        OPTIONAL MATCH (e0)-[:SUBJECT_OF|OBJECT_OF]-(a:Action)-[:SUBJECT_OF|OBJECT_OF]-(related:Entity)
        WHERE related.content IS NOT NULL AND related.content <> e0.content
        OPTIONAL MATCH (related)-[:FROM_MESSAGE]->(related_msg:Message)-[:PART_OF_SESSION]->(related_s:Session)-[:OWNED_BY]->(u)
        WITH u, current_sid, summary_results, concept_results, layer1_results, collect(DISTINCT {
            content: related_msg.content,
            time: related_msg.created_at,
            importance: related_msg.importance,
            layer: 'related',
            via: related.content,
            session_id: related_s.session_id
        }) AS layer2_results

        // Layer 3 fallback: salient raw messages across sessions (keep this as fallback only)
        OPTIONAL MATCH (salient_msg:Message)-[:PART_OF_SESSION]->(salient_s:Session)-[:OWNED_BY]->(u)
        WHERE salient_s.id <> current_sid
        WITH u, current_sid, summary_results, concept_results, layer1_results, layer2_results, collect(DISTINCT {
            content: salient_msg.content,
            time: salient_msg.created_at,
            importance: salient_msg.importance,
            layer: 'salient',
            session_id: salient_s.session_id
        }) AS salient_results

        // Layer 4: recent memories across user history (exclude current session)
        OPTIONAL MATCH (recent_msg:Message)-[:PART_OF_SESSION]->(recent_s:Session)-[:OWNED_BY]->(u)
        WHERE recent_msg.created_at > datetime() - duration({days: $recent_days})
          AND recent_s.id <> current_sid
        WITH summary_results, concept_results, layer1_results, layer2_results, salient_results, collect(DISTINCT {
            content: recent_msg.content,
            time: recent_msg.created_at,
            importance: recent_msg.importance,
            layer: 'recent',
            session_id: recent_s.session_id
        }) AS recent_results

        RETURN {
            summary: [r IN summary_results WHERE r.content IS NOT NULL],
            concept: [r IN concept_results WHERE r.content IS NOT NULL],
            direct: [r IN layer1_results WHERE r.content IS NOT NULL],
            related: [r IN layer2_results WHERE r.content IS NOT NULL],
            salient: [r IN salient_results WHERE r.content IS NOT NULL],
            recent: [r IN recent_results WHERE r.content IS NOT NULL]
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
                'summary': [], 'concept': [], 'direct': [], 'related': [], 'salient': [], 'recent': []
            }
        except Exception as e:
            logger.error(f"Auto-recall Cypher query failed: {e}")
            return {'summary': [], 'concept': [], 'direct': [], 'related': [], 'salient': [], 'recent': []}
    
    def _format_context(self, results: Dict, max_tokens: int = 1500, items_per_layer: int = 3) -> str:
        """Format recalled results into a compact context string."""
        lines = []
        token_count = 0
        
        # Process in order of priority.
        priorities = [
            ('summary', results.get('summary', []), '[Long-term summaries]'),
            ('concept', results.get('concept', []), '[Topic concepts]'),
            ('direct', results.get('direct', []), '[Direct memories]'),
            ('related', results.get('related', []), '[Related knowledge]'),
            ('salient', results.get('salient', []), '[Long-term memories]'),
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
