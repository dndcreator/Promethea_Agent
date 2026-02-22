"""
Cold-layer manager.

Use an LLM to compress conversation history into long-term summaries.
"""
import logging
from typing import List, Dict, Optional
from openai import OpenAI
from .api_settings import resolve_memory_api

logger = logging.getLogger(__name__)


class ColdLayerManager:
    """Cold-layer memory manager using LLM summarization."""
    
    def __init__(self, connector, config):
        """
        Initialize cold-layer manager.

        Args:
            connector: Neo4j connector.
            config: Project configuration object.
        """
        self.connector = connector
        self.config = config
        memory_api = resolve_memory_api(config)
        
        # Initialize LLM client for summarization.
        self.client = OpenAI(
            api_key=memory_api["api_key"],
            base_url=memory_api["base_url"]
        )
        
        # Summarization parameters.
        # Prefer cold-layer specific model if configured, otherwise reuse dialog model.
        self.summary_model = getattr(config.memory.cold_layer, "summary_model", None) or memory_api["model"]
        self.max_summary_length = config.memory.cold_layer.max_summary_length
        self.compression_threshold = config.memory.cold_layer.compression_threshold
        
        logger.info("Cold-layer manager initialized")
    
    def summarize_session(self, session_id: str, include_concepts: bool = True) -> Optional[str]:
        """
        Create a cold-layer summary node for a session.

        Args:
            session_id: Session ID.
            include_concepts: Whether to include warm-layer concepts as context.

        Returns:
            Summary node ID, or None on failure / skipped.
        """
        logger.info(f"Start generating summary for session {session_id}")
        
        # 1. Collect conversation messages.
        messages = self._get_session_messages(session_id)

        # 2. Fetch semantic snapshot (warm-first inputs).
        semantic = self._get_session_semantic_snapshot(session_id, include_concepts=include_concepts)
        concepts = semantic.get("concepts", [])

        # Gate: allow summary when either messages are sufficient or semantics are rich enough.
        has_rich_semantics = len(semantic.get("facts", [])) >= 3 or len(concepts) >= 2
        if len(messages) < 5 and not has_rich_semantics:
            logger.info(
                "Not enough evidence for summary (messages=%s concepts=%s facts=%s), skip",
                len(messages),
                len(concepts),
                len(semantic.get("facts", [])),
            )
            return None

        # 3. Call LLM to generate summary text.
        summary_text = self._generate_summary(messages, semantic)
        
        if not summary_text:
            logger.warning("Summary generation failed")
            return None
        
        # 4. Create summary node.
        summary_id = self._create_summary_node(session_id, summary_text, len(messages))
        
        logger.info(f"Summary node created: {summary_id}")
        return summary_id
    
    def _get_session_messages(self, session_id: str, skip: int = 0) -> List[Dict]:
        """
        Fetch conversation messages for a session.

        Args:
            session_id: Session ID.
            skip: Number of earliest messages to skip (for incremental fetch).
        """
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        WHERE m.layer = 0
        RETURN m.content as content, m.role as role, m.created_at as created_at
        ORDER BY m.created_at ASC
        SKIP $skip
        """
        
        results = self.connector.query(
            query,
            {
                "session_id": f"session_{session_id}",
                "skip": skip,
            },
        )
        return [dict(r) for r in results]
    
    def _get_session_concepts(self, session_id: str) -> List[str]:
        """Get concept texts for a session (from warm layer)."""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(c:Concept)
        RETURN c.content as content
        ORDER BY c.importance DESC
        LIMIT 10
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [r["content"] for r in results]
    
    def _generate_summary(self, messages: List[Dict], semantic: Dict) -> Optional[str]:
        """
        Generate a summary using the LLM.

        Args:
            messages: List of message dicts.
            concepts: Optional list of concept strings.

        Returns:
            Summary text, or None on failure.
        """
        prompt = self._build_summary_prompt(messages, semantic)
        
        try:
            response = self.client.chat.completions.create(
                model=self.summary_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a concise memory summarization assistant. "
                            "Prioritize stable semantic facts and concepts, then use raw dialog only to disambiguate."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,  # keep variance low to make summaries stable
                max_tokens=self.max_summary_length * 2,  # leave some room
            )
            
            summary = response.choices[0].message.content.strip()
            logger.info(
                "Cold-layer summary generated successfully, length=%s",
                len(summary),
            )
            return summary
            
        except Exception as e:
            logger.error(f"LLM summary generation failed: {e}")
            return None
    
    def _create_summary_node(self, session_id: str, summary_text: str, message_count: int) -> Optional[str]:
        """
        Create a summary node in Neo4j.

        Args:
            session_id: Session ID.
            summary_text: Summary content.
            message_count: Number of messages summarized.

        Returns:
            Summary node ID.
        """
        from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType
        import uuid
        from datetime import datetime
        
        # Create summary node.
        summary_id = f"summary_{uuid.uuid4().hex[:12]}"
        summary_node = Neo4jNode(
            id=summary_id,
            type=NodeType.SUMMARY,
            content=summary_text,
            layer=2,  # cold layer
            importance=0.9,  # summaries are usually very important
            properties={
                "session_id": session_id,
                "message_count": message_count,
            }
        )
        
        self.connector.create_node(summary_node)
        logger.info(f"Created summary node: {summary_id}")
        
        # Link summary node to session.
        session_relation = Neo4jRelation(
            type=RelationType.SUMMARIZES,
            source_id=summary_id,
            target_id=f"session_{session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return summary_id
    
    def get_summaries(self, session_id: str) -> List[Dict]:
        """Get all summaries for a session."""
        query = """
        MATCH (s:Session {id: $session_id})
        MATCH (sum:Summary)
        WHERE EXISTS { MATCH (sum)-[r]->(s) WHERE type(r) = 'SUMMARIZES' }
        RETURN sum.id as id, sum.content as content, 
               sum.importance as importance, 
               coalesce(properties(sum)['message_count'], 0) as message_count,
               sum.created_at as created_at
        ORDER BY sum.created_at DESC
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def get_summary_by_id(self, summary_id: str) -> Optional[Dict]:
        """Get a specific summary by its ID."""
        query = """
        MATCH (sum:Summary {id: $summary_id})
        RETURN
               sum.id as id,
               sum.content as content,
               sum.importance as importance,
               coalesce(properties(sum)['session_id'], '') as session_id,
               coalesce(properties(sum)['message_count'], 0) as message_count,
               sum.created_at as created_at
        """
        
        results = self.connector.query(query, {"summary_id": summary_id})
        return dict(results[0]) if results else None
    
    def should_create_summary(self, session_id: str) -> bool:
        """
        Decide whether a new summary should be created.

        Args:
            session_id: Session ID.

        Returns:
            True if a summary should be created.
        """
        # Check total message count.
        messages = self._get_session_messages(session_id)
        semantic = self._get_session_semantic_snapshot(session_id, include_concepts=True)
        concepts = semantic.get("concepts", [])
        facts = semantic.get("facts", [])
        has_rich_semantics = len(facts) >= max(2, self.compression_threshold // 10) or len(concepts) >= 2

        if len(messages) < self.compression_threshold and not has_rich_semantics:
            return False
        
        # Check if there is a recent summary and whether enough new messages were added.
        summaries = self.get_summaries(session_id)
        if summaries:
            latest_summary = summaries[0]
            summarized_count = latest_summary.get('message_count', 0)
            new_messages = len(messages) - summarized_count
            
            # If new messages less than half of threshold and semantics not rich, skip.
            if new_messages < self.compression_threshold // 2 and not has_rich_semantics:
                return False
        
        return True
    
    def create_incremental_summary(self, session_id: str) -> Optional[str]:
        """
        Create an incremental summary that only summarizes new messages.

        Args:
            session_id: Session ID.

        Returns:
            Summary node ID.
        """
        logger.info(f"Creating incremental summary for session {session_id}")
        
        # Get existing summaries.
        summaries = self.get_summaries(session_id)
        
        if not summaries:
            # No previous summaries: fall back to full summarization (skip=0).
            return self.summarize_session(session_id)
        
        # Compute how many messages were already summarized.
        latest_summary = summaries[0]
        summarized_count = latest_summary.get('message_count', 0)
        
        # Fetch only new messages (use SKIP for performance).
        new_messages = self._get_session_messages(session_id, skip=summarized_count)
        
        if len(new_messages) < 5:
            logger.info("Not enough new messages, skip incremental summary")
            return None
        
        semantic = self._get_session_semantic_snapshot(session_id, include_concepts=True)
        # Generate incremental summary, using previous summary + fresh semantics.
        previous_summary = latest_summary['content']
        incremental_summary = self._generate_incremental_summary(
            previous_summary, 
            new_messages,
            semantic,
        )
        
        if not incremental_summary:
            return None
        
        # Create new summary node.
        # New total message count = previous total + new message count.
        total_count = summarized_count + len(new_messages)
        summary_id = self._create_summary_node(
            session_id, 
            incremental_summary,
            total_count
        )
        
        return summary_id
    
    def _generate_incremental_summary(self, previous_summary: str, new_messages: List[Dict], semantic: Dict) -> Optional[str]:
        """Generate an incremental summary based on previous summary and new messages."""
        delta_messages = self._format_messages_for_prompt(new_messages, limit=30)
        prompt = (
            "Here is the previous dialog summary:\n"
            f"{previous_summary}\n\n"
            "New semantic evidence:\n"
            f"{self._format_semantic_for_prompt(semantic)}\n\n"
            "Recent dialog delta:\n"
            f"{delta_messages}\n\n"
            f"Please merge into an updated memory summary under {self.max_summary_length} characters."
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.summary_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a concise dialog summarization assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=self.max_summary_length * 2,
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Incremental summary generation failed: {e}")
            return None

    def _get_session_semantic_snapshot(self, session_id: str, include_concepts: bool = True) -> Dict[str, List]:
        """Collect semantic memory signals for summary generation."""
        concepts = self._get_session_concepts(session_id) if include_concepts else []
        entities = self._get_session_entities(session_id)
        facts = self._get_session_facts(session_id)
        return {
            "concepts": concepts,
            "entities": entities,
            "facts": facts,
        }

    def _get_session_entities(self, session_id: str) -> List[Dict]:
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)<-[:FROM_MESSAGE]-(e:Entity)
        RETURN e.content AS content,
               count(m) AS mentions,
               max(coalesce(e.importance, 0.0)) AS importance
        ORDER BY mentions DESC, importance DESC
        LIMIT 20
        """
        return [dict(r) for r in self.connector.query(query, {"session_id": f"session_{session_id}"})]

    def _get_session_facts(self, session_id: str) -> List[Dict]:
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)<-[:FROM_MESSAGE]-(a:Action)
        OPTIONAL MATCH (sub:Entity)-[:SUBJECT_OF]->(a)
        OPTIONAL MATCH (a)-[:OBJECT_OF]->(obj:Entity)
        RETURN
            coalesce(sub.content, '') AS subject,
            a.content AS predicate,
            coalesce(obj.content, '') AS object,
            count(m) AS mentions,
            max(coalesce(a.importance, 0.0)) AS importance
        ORDER BY mentions DESC, importance DESC
        LIMIT 20
        """
        rows = self.connector.query(query, {"session_id": f"session_{session_id}"})
        # Keep only rows with at least predicate.
        return [dict(r) for r in rows if r.get("predicate")]

    def _format_messages_for_prompt(self, messages: List[Dict], limit: int = 40) -> str:
        if not messages:
            return "(none)"
        tail = messages[-limit:]
        return "\n".join([f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in tail])

    def _format_semantic_for_prompt(self, semantic: Dict) -> str:
        concepts = semantic.get("concepts", []) or []
        entities = semantic.get("entities", []) or []
        facts = semantic.get("facts", []) or []

        parts = []
        if concepts:
            parts.append("Concepts: " + " | ".join(concepts[:12]))
        if entities:
            ent_text = ", ".join(
                [f"{e.get('content')} (x{int(e.get('mentions', 0) or 0)})" for e in entities[:15] if e.get("content")]
            )
            if ent_text:
                parts.append("Entities: " + ent_text)
        if facts:
            fact_text = "; ".join(
                [
                    f"{f.get('subject', '').strip()} - {f.get('predicate', '').strip()} - {f.get('object', '').strip()} "
                    f"(x{int(f.get('mentions', 0) or 0)})"
                    for f in facts[:12]
                    if f.get("predicate")
                ]
            )
            if fact_text:
                parts.append("Facts: " + fact_text)
        return "\n".join(parts) if parts else "(no semantic snapshot)"

    def _build_summary_prompt(self, messages: List[Dict], semantic: Dict) -> str:
        semantic_text = self._format_semantic_for_prompt(semantic)
        conversation_text = self._format_messages_for_prompt(messages, limit=40)
        return (
            "Create a compact long-term memory summary for this user session.\n"
            "Priority order:\n"
            "1) Stable semantic facts and concepts\n"
            "2) User goals/preferences/identity\n"
            "3) Decisions and pending actions\n"
            "Use raw dialog only to disambiguate details.\n\n"
            "Semantic memory snapshot:\n"
            f"{semantic_text}\n\n"
            "Recent dialog (for disambiguation only):\n"
            f"{conversation_text}\n\n"
            f"Keep it under {self.max_summary_length} characters."
        )


def create_cold_layer_manager(connector):
    """
    Factory function to create a ColdLayerManager.

    Args:
        connector: Neo4j connector.

    Returns:
        ColdLayerManager instance, or None if memory is disabled.
    """
    try:
        from config import load_config
        config = load_config()
        
        # Check whether memory system is enabled.
        if not config.memory.enabled:
            logger.info("Memory system disabled")
            return None
        
        return ColdLayerManager(connector, config)
        
    except Exception as e:
        logger.warning(f"Cold-layer manager initialization failed: {e}")
        return None

