"""Memory forgetting/decay controller."""

import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from .neo4j_connector import Neo4jConnector

logger = logging.getLogger(__name__)


class ForgettingManager:
    """Manager for memory forgetting and decay."""
    
    def __init__(self, connector: Neo4jConnector):
        self.connector = connector
        
        # Time-decay curve parameters: days -> decay factor.
        self.decay_curve = {
            1: 1.0,      # within 1 day: 100%
            7: 0.9,      # within 1 week: 90%
            30: 0.7,     # within 1 month: 70%
            90: 0.5,     # within 3 months: 50%
            365: 0.3,    # within 1 year: 30%
            float("inf"): 0.2,  # after 1 year: 20% (minimum)
        }
        
        # Access-boost parameters.
        self.access_boost = 0.05  # each 10 accesses adds 5%
        self.max_importance = 1.0
        
        # Cleanup thresholds.
        self.min_importance = 0.15  # below 15% is considered forgotten
        self.cleanup_batch = 100    # delete at most 100 nodes per run

        # Episodic message retention (hot-layer raw text).
        # Messages are deleted only when:
        # 1) old enough, and
        # 2) already covered by at least one summary in that session.
        self.message_retention_days = 30
        self.message_cleanup_batch = 200
        try:
            from config import load_config

            cfg = load_config()
            hot_cfg = getattr(cfg.memory, "hot_layer", None)
            if hot_cfg is not None:
                self.message_retention_days = max(
                    1, int(getattr(hot_cfg, "message_retention_days", self.message_retention_days))
                )
                self.message_cleanup_batch = max(
                    20, int(getattr(hot_cfg, "message_cleanup_batch", self.message_cleanup_batch))
                )
        except Exception:
            # Keep defaults when config load is unavailable.
            pass
    
    def calculate_decay_factor(self, days_passed: float) -> float:
        """
        Calculate time-decay factor.

        Args:
            days_passed: Number of days passed.

        Returns:
            Decay factor in range [0.2, 1.0].
        """
        for threshold, factor in sorted(self.decay_curve.items()):
            if days_passed <= threshold:
                return factor
        return 0.2

    def _to_python_datetime(self, value):
        """Best-effort conversion for Neo4j temporal values."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return None
        if hasattr(value, "to_native"):
            try:
                native = value.to_native()
                if isinstance(native, datetime):
                    return native
            except Exception:
                return None
        return None
    
    def apply_time_decay(self, session_id: str = None) -> Dict:
        """
        Apply time-based decay to all eligible nodes.

        Args:
            session_id: Optional; if provided, only process nodes of that session.

        Returns:
            Statistics about the update.
        """
        try:
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})
                MATCH (n)
                WHERE n.layer IN [0, 1]  // only base-layer and warm-layer
                AND n.created_at IS NOT NULL
                AND (
                    EXISTS { MATCH (n)-[:PART_OF_SESSION]->(s) }
                    OR EXISTS { MATCH (n)-[:FROM_MESSAGE]->(:Message)-[:PART_OF_SESSION]->(s) }
                )
                RETURN n.id as id, n.created_at as created_at, 
                       n.importance as importance, n.access_count as access_count
                """
                params = {"session_id": f"session_{session_id}"}
            else:
                query = """
                MATCH (n)
                WHERE n.layer IN [0, 1]
                AND n.created_at IS NOT NULL
                RETURN n.id as id, n.created_at as created_at,
                       n.importance as importance, n.access_count as access_count
                """
                params = {}
            
            nodes = self.connector.query(query, params)
            
            now = datetime.now(timezone.utc)
            updated_count = 0
            
            for node in nodes:
                created_at = self._to_python_datetime(node['created_at'])
                if created_at is None:
                    continue
                
                # Normalize timezone-awareness before subtraction.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                else:
                    created_at = created_at.astimezone(timezone.utc)

                days_passed = (now - created_at).total_seconds() / 86400
                
                decay_factor = self.calculate_decay_factor(days_passed)
                
                # Compute access boost (each 10 accesses adds 5%, capped at 20%).
                access_count = node.get('access_count', 0)
                access_boost = min(0.2, (access_count // 10) * self.access_boost)
                
                original_importance = node.get('importance', 0.5)
                
                # new_importance = original * time_decay + access_boost
                new_importance = min(
                    self.max_importance,
                    original_importance * decay_factor + access_boost
                )
                
                update_query = """
                MATCH (n {id: $id})
                SET n.importance = $importance
                """
                self.connector.query(update_query, {
                    'id': node['id'],
                    'importance': new_importance
                })
                
                updated_count += 1
            
            logger.info(f"Time-decay update complete: {updated_count} nodes")
            
            return {
                'updated_count': updated_count,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Time-decay update failed: {e}")
            return {
                'updated_count': 0,
                'status': 'error',
                'error': str(e)
            }
    
    def cleanup_forgotten(self, session_id: str = None) -> Dict:
        """
        Clean up nodes that are considered forgotten (importance < min_importance).

        Args:
            session_id: Optional; if provided, clean only that session.

        Returns:
            Statistics about deleted nodes.
        """
        try:
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})
                MATCH (n)
                WHERE n.layer = 0  // only base-layer
                AND NOT n:Message  // keep original messages (filter by labels)
                AND n.importance < $min_importance
                AND (
                    EXISTS { MATCH (n)-[:PART_OF_SESSION]->(s) }
                    OR EXISTS { MATCH (n)-[:FROM_MESSAGE]->(:Message)-[:PART_OF_SESSION]->(s) }
                )
                RETURN n.id as id
                LIMIT $limit
                """
                params = {
                    "session_id": f"session_{session_id}",
                    "min_importance": self.min_importance,
                    "limit": self.cleanup_batch
                }
            else:
                query = """
                MATCH (n)
                WHERE n.layer = 0
                AND NOT n:Message
                AND n.importance < $min_importance
                RETURN n.id as id
                LIMIT $limit
                """
                params = {
                    "min_importance": self.min_importance,
                    "limit": self.cleanup_batch
                }
            
            nodes_to_delete = self.connector.query(query, params)
            
            deleted_count = 0
            for node in nodes_to_delete:
                # Delete node and all its relations.
                delete_query = """
                MATCH (n {id: $id})
                DETACH DELETE n
                """
                self.connector.query(delete_query, {'id': node['id']})
                deleted_count += 1
            
            logger.info(f"Forgotten-node cleanup complete: {deleted_count} nodes")
            
            return {
                'deleted_count': deleted_count,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Forgotten-node cleanup failed: {e}")
            return {
                'deleted_count': 0,
                'status': 'error',
                'error': str(e)
            }

    def cleanup_episodic_messages(self, session_id: str = None) -> Dict:
        """
        Cleanup old raw Message nodes that have already been summarized.

        Rules:
        - only Message nodes
        - only older than message_retention_days
        - only earliest messages that are already covered by summary.message_count
        """
        try:
            if session_id:
                session_ids = [f"session_{session_id}"]
            else:
                rows = self.connector.query("MATCH (s:Session) RETURN s.id AS id")
                session_ids = [str(r.get("id")) for r in rows if r.get("id")]

            deleted_total = 0
            for sid in session_ids:
                if deleted_total >= self.message_cleanup_batch:
                    break
                deleted_total += self._cleanup_episodic_messages_for_session(
                    sid,
                    self.message_cleanup_batch - deleted_total,
                )

            if deleted_total:
                logger.info("Episodic message cleanup complete: %s nodes", deleted_total)
            return {"deleted_count": deleted_total, "status": "success"}
        except Exception as e:
            logger.error(f"Episodic message cleanup failed: {e}")
            return {"deleted_count": 0, "status": "error", "error": str(e)}

    def _cleanup_episodic_messages_for_session(self, session_node_id: str, limit: int) -> int:
        if limit <= 0:
            return 0
        # Get latest summary coverage for this session.
        summary_row = self.connector.query(
            """
            MATCH (sum:Summary)-[:SUMMARIZES]->(s:Session {id: $session_id})
            RETURN coalesce(max(sum.message_count), 0) AS covered_count
            """,
            {"session_id": session_node_id},
        )
        covered_count = int(summary_row[0].get("covered_count", 0) or 0) if summary_row else 0
        if covered_count <= 0:
            return 0

        rows = self.connector.query(
            """
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
            WHERE m.created_at < datetime() - duration({days: $retention_days})
            WITH m
            ORDER BY m.created_at ASC
            WITH collect(m) AS aged_msgs
            MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(allm:Message)
            WITH aged_msgs, allm
            ORDER BY allm.created_at ASC
            WITH aged_msgs, collect(allm) AS ordered_msgs
            WITH aged_msgs, ordered_msgs[0..$covered_count] AS summarized_msgs
            WITH [m IN aged_msgs WHERE m IN summarized_msgs][0..$limit] AS deletable
            UNWIND deletable AS d
            DETACH DELETE d
            RETURN count(d) AS deleted_count
            """,
            {
                "session_id": session_node_id,
                "retention_days": int(self.message_retention_days),
                "covered_count": int(covered_count),
                "limit": int(limit),
            },
        )
        if not rows:
            return 0
        return int(rows[0].get("deleted_count", 0) or 0)
    
    def get_forgetting_stats(self, session_id: str = None) -> Dict:
        """
        Get statistics for forgetting/decay.

        Args:
            session_id: Optional; if provided, compute stats for that session only.

        Returns:
            Statistics dictionary.
        """
        try:
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})
                MATCH (n)
                WHERE n.layer IN [0, 1]
                AND (
                    EXISTS { MATCH (n)-[:PART_OF_SESSION]->(s) }
                    OR EXISTS { MATCH (n)-[:FROM_MESSAGE]->(:Message)-[:PART_OF_SESSION]->(s) }
                )
                RETURN 
                    count(n) as total_nodes,
                    avg(n.importance) as avg_importance,
                    sum(CASE WHEN n.importance < 0.3 THEN 1 ELSE 0 END) as weak_nodes,
                    sum(CASE WHEN n.importance >= 0.7 THEN 1 ELSE 0 END) as strong_nodes
                """
                params = {"session_id": f"session_{session_id}"}
            else:
                query = """
                MATCH (n)
                WHERE n.layer IN [0, 1]
                RETURN 
                    count(n) as total_nodes,
                    avg(n.importance) as avg_importance,
                    sum(CASE WHEN n.importance < 0.3 THEN 1 ELSE 0 END) as weak_nodes,
                    sum(CASE WHEN n.importance >= 0.7 THEN 1 ELSE 0 END) as strong_nodes
                """
                params = {}
            
            result = self.connector.query(query, params)
            
            if result:
                stats = result[0]
                return {
                    'total_nodes': stats.get('total_nodes', 0),
                    'avg_importance': round(stats.get('avg_importance', 0), 3),
                    'weak_nodes': stats.get('weak_nodes', 0),
                    'strong_nodes': stats.get('strong_nodes', 0),
                    'status': 'success'
                }
            
            return {"status": "no_data"}
            
        except Exception as e:
            logger.error(f"Get forgetting stats failed: {e}")
            return {"status": "error", "error": str(e)}


def create_forgetting_manager(connector: Neo4jConnector) -> ForgettingManager:
    """Factory function to create a ForgettingManager."""
    return ForgettingManager(connector)

