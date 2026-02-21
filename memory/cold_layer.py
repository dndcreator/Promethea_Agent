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
        
        if len(messages) < 5:
            logger.info(f"Not enough messages ({len(messages)} < 5), skip summary")
            return None
        
        # 2. Optionally fetch concept nodes from warm layer.
        concepts = []
        if include_concepts:
            concepts = self._get_session_concepts(session_id)
        
        # 3. Call LLM to generate summary text.
        summary_text = self._generate_summary(messages, concepts)
        
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
    
    def _generate_summary(self, messages: List[Dict], concepts: List[str]) -> Optional[str]:
        """
        Generate a summary using the LLM.

        Args:
            messages: List of message dicts.
            concepts: Optional list of concept strings.

        Returns:
            Summary text, or None on failure.
        """
        # Build conversation history text.
        conversation_text = "\n".join(
            [
                f"{msg['role']}: {msg['content']}"
                for msg in messages
            ]
        )
        
        # Build LLM prompt.
        prompt = (
            "Please write a concise summary for the following dialog.\n"
            "Focus on:\n"
            "1. Main topics and content.\n"
            "2. The user's key needs or questions.\n"
            "3. Important information and conclusions.\n\n"
            f"Conversation:\n{conversation_text}\n"
        )
        
        # If we have concept information, add it to the prompt.
        if concepts:
            concepts_text = " | ".join(concepts)
            prompt += f"\n\nDetected topics: {concepts_text}\n"
        
        prompt += (
            f"\nPlease keep the summary under {self.max_summary_length} characters."
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
        MATCH (s:Session {id: $session_id})<-[:SUMMARIZES]-(sum:Summary)
        RETURN sum.id as id, sum.content as content, 
               sum.importance as importance, 
               sum.message_count as message_count,
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
               sum.session_id as session_id,
               sum.message_count as message_count,
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
        
        if len(messages) < self.compression_threshold:
            return False
        
        # Check if there is a recent summary and whether enough new messages were added.
        summaries = self.get_summaries(session_id)
        if summaries:
            latest_summary = summaries[0]
            summarized_count = latest_summary.get('message_count', 0)
            new_messages = len(messages) - summarized_count
            
            # If new messages less than half of threshold, skip.
            if new_messages < self.compression_threshold // 2:
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
        
        # Generate incremental summary, using previous summary as context.
        previous_summary = latest_summary['content']
        incremental_summary = self._generate_incremental_summary(
            previous_summary, 
            new_messages
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
    
    def _generate_incremental_summary(self, previous_summary: str, new_messages: List[Dict]) -> Optional[str]:
        """Generate an incremental summary based on previous summary and new messages."""
        conversation_text = "\n".join(
            [
                f"{msg['role']}: {msg['content']}"
                for msg in new_messages
            ]
        )
        
        prompt = (
            "Here is the previous dialog summary:\n"
            f"{previous_summary}\n\n"
            "Here is the new dialog content:\n"
            f"{conversation_text}\n\n"
            f"Please merge them into an updated summary, under {self.max_summary_length} characters."
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

