"""
Neo4j connection and query helper.
"""
import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Transaction

from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType

logger = logging.getLogger(__name__)


class Neo4jConnector:
    """Thin wrapper around Neo4j driver operations used by memory modules."""

    def __init__(self, config):
        self.config = config
        self.driver = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
            max_connection_lifetime=config.max_connection_lifetime,
            max_connection_pool_size=config.max_connection_pool_size,
            connection_timeout=config.connection_timeout,
            # Fail fast if DB is down; avoid long startup blocking.
            max_transaction_retry_time=1.0,
        )
        self._create_constraints()
        logger.info(f"Neo4j connector initialized: {config.uri}")

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connector closed")

    def _create_constraints(self):
        with self.driver.session(database=self.config.database) as session:
            # Probe once first; if this fails we want a single fast failure.
            session.run("RETURN 1 AS ok").consume()

            constraints = [
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT action_id IF NOT EXISTS FOR (n:Action) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT message_id IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (n:Session) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT time_id IF NOT EXISTS FOR (n:Time) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT location_id IF NOT EXISTS FOR (n:Location) REQUIRE n.id IS UNIQUE",
            ]

            indexes = [
                "CREATE INDEX entity_content IF NOT EXISTS FOR (n:Entity) ON (n.content)",
                "CREATE INDEX action_content IF NOT EXISTS FOR (n:Action) ON (n.content)",
                "CREATE INDEX time_content IF NOT EXISTS FOR (n:Time) ON (n.content)",
                "CREATE INDEX location_content IF NOT EXISTS FOR (n:Location) ON (n.content)",
                "CREATE INDEX message_session IF NOT EXISTS FOR (n:Message) ON (n.session_id)",
                "CREATE INDEX message_created IF NOT EXISTS FOR (n:Message) ON (n.created_at)",
                "CREATE INDEX node_importance IF NOT EXISTS FOR (n:Entity) ON (n.importance)",
                "CREATE INDEX node_layer IF NOT EXISTS FOR (n:Entity) ON (n.layer)",
            ]

            for statement in constraints:
                try:
                    session.run(statement).consume()
                except Exception as e:
                    logger.debug(f"Constraint create skipped/failed: {e}")

            for statement in indexes:
                try:
                    session.run(statement).consume()
                except Exception as e:
                    logger.debug(f"Index create skipped/failed: {e}")

    def create_node(self, node: Neo4jNode) -> str:
        with self.driver.session(database=self.config.database) as session:
            return session.execute_write(self._create_node_tx, node)

    @staticmethod
    def _create_node_tx(tx: Transaction, node: Neo4jNode) -> str:
        if not node.id:
            import uuid

            node.id = f"{node.type.value.lower()}_{uuid.uuid4().hex[:12]}"

        query = f"""
        MERGE (n:{node.type.value} {{id: $id}})
        ON CREATE SET
            n.content = $content,
            n.layer = $layer,
            n.importance = $importance,
            n.access_count = $access_count,
            n.created_at = datetime($created_at)
        ON MATCH SET
            n.access_count = n.access_count + 1
        SET n += $properties
        RETURN n.id as id
        """

        result = tx.run(
            query,
            id=node.id,
            content=node.content,
            layer=node.layer,
            importance=node.importance,
            access_count=node.access_count,
            created_at=node.created_at.isoformat(),
            properties=node.properties,
        )
        record = result.single()
        return record["id"] if record else node.id

    def create_relation(self, relation: Neo4jRelation) -> bool:
        with self.driver.session(database=self.config.database) as session:
            return session.execute_write(self._create_relation_tx, relation)

    @staticmethod
    def _create_relation_tx(tx: Transaction, relation: Neo4jRelation) -> bool:
        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        MERGE (a)-[r:{relation.type.value}]->(b)
        ON CREATE SET
            r.weight = $weight,
            r.created_at = datetime($created_at)
        SET r += $properties
        RETURN r
        """
        try:
            result = tx.run(
                query,
                source_id=relation.source_id,
                target_id=relation.target_id,
                weight=relation.weight,
                created_at=relation.created_at.isoformat(),
                properties=relation.properties,
            )
            return result.single() is not None
        except Exception as e:
            logger.error(f"Create relation failed: {e}")
            return False

    def query(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self.driver.session(database=self.config.database) as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        results = self.query("MATCH (n {id: $id}) RETURN n", {"id": node_id})
        return results[0]["n"] if results else None

    def find_node_by_content(self, node_type: NodeType, content: str) -> Optional[str]:
        query = f"MATCH (n:{node_type.value} {{content: $content}}) RETURN n.id as id LIMIT 1"
        results = self.query(query, {"content": content})
        return results[0]["id"] if results else None

    def get_neighbors(
        self,
        node_id: str,
        relation_type: Optional[RelationType] = None,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        rel_pattern = f":{relation_type.value}" if relation_type else ""
        if direction == "out":
            pattern = f"(n {{id: $id}})-[r{rel_pattern}]->(m)"
        elif direction == "in":
            pattern = f"(n {{id: $id}})<-[r{rel_pattern}]-(m)"
        else:
            pattern = f"(n {{id: $id}})-[r{rel_pattern}]-(m)"

        results = self.query(f"MATCH {pattern} RETURN m, r", {"id": node_id})
        return [{"node": row["m"], "relation": row["r"]} for row in results]

    def delete_node(self, node_id: str) -> bool:
        try:
            self.query("MATCH (n {id: $id}) DETACH DELETE n", {"id": node_id})
            return True
        except Exception as e:
            logger.error(f"Delete node failed: {e}")
            return False

    def clear_database(self):
        self.query("MATCH (n) DETACH DELETE n")
        logger.warning("Database cleared")

    def show_indexes(self) -> List[Dict[str, Any]]:
        return self.query("SHOW INDEXES")

    def get_statistics(self) -> Dict[str, int]:
        node_stats = self.query("MATCH (n) RETURN labels(n)[0] as type, count(n) as count")
        stats = {row["type"]: row["count"] for row in node_stats if row["type"]}
        rel_stats = self.query("MATCH ()-[r]->() RETURN count(r) as rel_count")
        stats["_relationships"] = rel_stats[0]["rel_count"] if rel_stats else 0
        return stats


class Neo4jConnectionPool:
    """Neo4j connector singleton."""

    _instance = None
    _connector = None

    @classmethod
    def get_connector(cls, config=None):
        """Get or initialize Neo4j connector singleton."""
        if cls._connector is None:
            if config is None:
                from config import load_config

                main_config = load_config()
                config = main_config.memory.neo4j

            if not getattr(config, "enabled", False):
                logger.info("Neo4j memory is disabled by config, skip connector initialization")
                return None

            try:
                cls._connector = Neo4jConnector(config)
            except Exception as e:
                logger.warning(f"Neo4j connector initialization failed, running without memory backend: {e}")
                cls._connector = None
        return cls._connector

    @classmethod
    def close(cls):
        if cls._connector:
            cls._connector.close()
            cls._connector = None
