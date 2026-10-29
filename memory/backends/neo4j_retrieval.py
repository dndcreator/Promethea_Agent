"""Owned memory views and rebuildable vector indexes inside the existing graph."""
from __future__ import annotations

import hashlib
from typing import Any

from memory.session_scope import user_node_id


OWNED = """EXISTS { MATCH (m)-[:PART_OF_SESSION|SUMMARIZES]->(:Session)-[:OWNED_BY]->(:User {id: $uid}) }"""
ACTIVE = """coalesce(m.status, 'active') = 'active' AND m.superseded_by IS NULL"""
MEMORY = """((m:Summary OR m:Concept OR (m:Message AND m.memory_type IS NOT NULL AND m.memory_type <> 'working'))
    AND m.content IS NOT NULL AND trim(m.content) <> '')"""
RETURN_ROW = """m.id AS memory_id, m.content AS content,
    CASE WHEN m:Summary THEN 'summary' WHEN m:Concept THEN 'concept'
         ELSE coalesce(m.target_memory_layer, 'direct') END AS source_layer,
    coalesce(m.memory_type, CASE WHEN m:Message THEN 'episodic' ELSE 'semantic' END) AS memory_type,
    coalesce(m.importance, 0.6) AS importance, toString(m.created_at) AS created_at,
    toString(coalesce(m.updated_at, m.created_at)) AS updated_at,
    m.session_id AS source_session, coalesce(m.status, 'active') AS status,
    m.semantic_keys AS semantic_keys, m.superseded_by AS superseded_by,
    m.supersedes AS supersedes, m.conflict_flag AS conflict_flag,
    m.community_id AS community_id, m.cluster_id AS cluster_id,
    m.revision_chain_id AS revision_chain_id, m.memory_relationship AS memory_relationship"""


class Neo4jVectorIndex:
    def __init__(self, connector: Any):
        self.connector = connector

    @staticmethod
    def namespace(user_id: str, identity: str) -> tuple[str, str, str]:
        owner = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        digest = owner + "_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        return f"MemoryVector_{digest}", f"memory_vector_{digest}", f"embedding_{digest}"

    def pending(self, user_id: str, identity: str, limit: int) -> list[dict]:
        label, _, prop = self.namespace(user_id, identity)
        self.connector.query(f"""
            MATCH (m:{label}) WHERE NOT ({OWNED} AND {ACTIVE} AND {MEMORY})
              OR m.{prop}_text <> m.content
            REMOVE m:{label} SET m.{prop} = null, m.{prop}_text = null
        """, {"uid": user_node_id(user_id)})
        # Content equality is a revision fence, including writes outside this adapter.
        return self.connector.query(f"""
            MATCH (m) WHERE {OWNED} AND {ACTIVE} AND {MEMORY}
              AND (NOT m:{label} OR m.{prop} IS NULL OR m.{prop}_text IS NULL OR m.{prop}_text <> m.content)
            RETURN m.id AS memory_id, m.content AS content
            ORDER BY m.id LIMIT $limit
        """, {"uid": user_node_id(user_id), "limit": limit}) or []

    def write(self, user_id: str, identity: str, rows: list[dict], vectors: list[list[float]]) -> int:
        label, index, prop = self.namespace(user_id, identity)
        self.connector.query(f"""CREATE VECTOR INDEX {index} IF NOT EXISTS FOR (m:{label}) ON m.{prop}
            OPTIONS {{indexConfig: {{`vector.dimensions`: {len(vectors[0])}, `vector.similarity_function`: 'cosine'}}}}""")
        values = [{**row, "vector": vector} for row, vector in zip(rows, vectors)]
        result = self.connector.query(f"""
            UNWIND $rows AS row
            MATCH (m {{id: row.memory_id}})
            WHERE {OWNED} AND {ACTIVE} AND {MEMORY} AND m.content = row.content
            SET m:{label}, m.{prop} = row.vector, m.{prop}_text = row.content
            RETURN count(m) AS written
        """, {"uid": user_node_id(user_id), "rows": values})
        return int((result or [{}])[0].get("written", 0))

    def counts(self, user_id: str, identity: str) -> dict:
        label, _, prop = self.namespace(user_id, identity)
        result = self.connector.query(f"""
            MATCH (m) WHERE {OWNED} AND {ACTIVE} AND {MEMORY}
            RETURN count(m) AS total, count(CASE WHEN m:{label} AND m.{prop} IS NOT NULL AND m.{prop}_text = m.content THEN 1 END) AS indexed
        """, {"uid": user_node_id(user_id)})
        return dict((result or [{"total": 0, "indexed": 0}])[0])

    def is_online(self, user_id: str, identity: str) -> bool:
        _, index, _ = self.namespace(user_id, identity)
        rows = self.connector.query("SHOW INDEXES YIELD name, state WHERE name = $index RETURN state", {"index": index}) or []
        return bool(rows and rows[0].get("state") == "ONLINE")

    def search(self, user_id: str, identity: str, vector: list[float], limit: int, threshold: float) -> list[dict]:
        label, index, prop = self.namespace(user_id, identity)
        # Each ANN index is physically user-scoped, not global top-k then owner filtering.
        rows = self.connector.query(f"""
            CALL db.index.vector.queryNodes($index, $limit, $vector) YIELD node AS m, score
            WHERE m:{label} AND {OWNED} AND {ACTIVE} AND {MEMORY}
              AND m.{prop}_text = m.content AND score >= $threshold
            RETURN {RETURN_ROW}, score AS relevance_score
            ORDER BY score DESC, m.id
        """, {"index": index, "limit": limit, "vector": vector, "threshold": threshold,
               "uid": user_node_id(user_id)}) or []
        return [{**row, "owner_user_id": user_id, "retrieval_channels": ["vector"]} for row in rows]

    def prune(self, user_id: str, identity: str) -> bool:
        """Retire obsolete derived generations only after the replacement is complete."""
        import re
        label, index, prop = self.namespace(user_id, identity)
        owner = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        labels_prefix, props_prefix = f"MemoryVector_{owner}_", f"embedding_{owner}_"
        rows = self.connector.query(f"""
            MATCH (m) WHERE {OWNED}
            WITH m, [key IN keys(m) WHERE key STARTS WITH $props_prefix AND NOT key STARTS WITH $current_prop] AS obsolete,
                 [label IN labels(m) WHERE label STARTS WITH $labels_prefix AND label <> $label] AS old_labels
            WHERE size(obsolete) > 0 OR size(old_labels) > 0
            RETURN m.id AS id, obsolete, old_labels LIMIT 128
        """, {"uid": user_node_id(user_id), "props_prefix": props_prefix,
               "current_prop": prop, "labels_prefix": labels_prefix, "label": label}) or []
        for row in rows:
            labels = [value for value in row["old_labels"] if re.fullmatch(r"MemoryVector_[0-9a-f]{16}_[0-9a-f]{16}", value)]
            remove = " REMOVE " + ", ".join(f"m:{value}" for value in labels) if labels else ""
            self.connector.query(f"MATCH (m {{id: $id}}) WHERE {OWNED} SET m += $removed {remove}",
                                 {"uid": user_node_id(user_id), "id": row["id"], "removed": {key: None for key in row["obsolete"]}})
        if rows:
            return False
        indexes = self.connector.query("SHOW INDEXES YIELD name WHERE name STARTS WITH $prefix AND name <> $current RETURN name",
                                       {"prefix": f"memory_vector_{owner}_", "current": index}) or []
        for row in indexes:
            if re.fullmatch(r"memory_vector_[0-9a-f]{16}_[0-9a-f]{16}", row["name"]):
                self.connector.query(f"DROP INDEX {row['name']} IF EXISTS")
        return True
