"""
Warm-layer manager.

Cluster base-layer nodes into higher-level topic concept nodes.
"""
import logging
import json
from typing import List, Dict, Optional
from openai import OpenAI
from .api_settings import resolve_memory_api

logger = logging.getLogger(__name__)


class WarmLayerManager:
    """Warm-layer memory manager for semantic clustering."""
    
    def __init__(self, connector, config):
        """
        Initialize warm-layer manager.

        Args:
            connector: Neo4j connector.
            config: Project configuration object.
        """
        self.connector = connector
        self.config = config
        memory_api = resolve_memory_api(config)
        
        # Initialize LLM client (used for clustering prompts).
        self.client = OpenAI(
            api_key=memory_api["api_key"],
            base_url=memory_api["base_url"]
        )
        
        # LLM clustering parameters.
        self.min_cluster_size = config.memory.warm_layer.min_cluster_size
        self.max_concepts = getattr(config.memory.warm_layer, "max_concepts", 100)
        self.cluster_model = memory_api["model"]
        
        logger.info("Warm-layer manager initialized")
    
    def _extract_json(self, text: str) -> Optional[dict]:
        """Best-effort extraction of JSON from model output (supports ```json fences)."""
        if not text:
            return None
        s = text.strip()
        if "```json" in s:
            try:
                s = s.split("```json", 1)[1].split("```", 1)[0].strip()
            except Exception:
                pass
        elif "```" in s:
            # Some models wrap content in ``` fences without specifying json.
            try:
                s = s.split("```", 1)[1].split("```", 1)[0].strip()
            except Exception:
                pass

        # Take the outer-most object.
        if "{" in s and "}" in s:
            s = s[s.find("{"): s.rfind("}") + 1]
        try:
            return json.loads(s)
        except Exception:
            return None

    def _llm_cluster_entities(self, session_id: str, entities: List[Dict]) -> Optional[List[Dict]]:
        """
        Ask the LLM to cluster entities into topic concepts.

        Returns:
            clusters: [{ "name": str, "entities": [str] }]
        """
        # Only pass minimal name strings to avoid very long prompts.
        entity_names = [e.get("content", "") for e in entities if e.get("content")]
        entity_names = list(dict.fromkeys(entity_names))  # de-duplicate, keep order

        max_clusters = min(12, max(3, self.max_concepts))
        prompt = (
            "You are an assistant for clustering entities into concise topic concepts.\n"
            "Instructions:\n"
            "1) Output MUST be strict JSON, no extra text.\n"
            '2) JSON format:\n'
            '   {\"clusters\":[{\"name\":\"topic name\",\"entities\":[\"entity1\",\"entity2\"]}],'
            ' \"unassigned\":[\"entities that cannot be grouped\"]}\n'
            f"3) Number of clusters should not be large (<= {max_clusters}), and each cluster "
            f"must contain at least {self.min_cluster_size} member entities. All entities must "
            "come from the input list.\n"
            "4) Topic names should be short and descriptive (<= 12 characters), such as "
            "\"work project\", \"tech stack\", \"family schedule\", etc.\n"
            "5) Do not invent entities that are not in the input list.\n\n"
            f"Session ID: {session_id}\n"
            f"Entity list (total {len(entity_names)}):\n"
            f"{json.dumps(entity_names, ensure_ascii=False)}\n"
        )
        messages = [
            {"role": "system", "content": "You are good at clustering entities into concise topics. Return strict JSON only."},
            {"role": "user", "content": prompt}
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.cluster_model,
                messages=messages,
                temperature=0.2,
                max_tokens=1200
            )
            text = (resp.choices[0].message.content or "").strip()
            data = self._extract_json(text)
            if not data or not isinstance(data, dict):
                return None
            clusters = data.get("clusters")
            if not isinstance(clusters, list):
                return None
            return clusters
        except Exception as e:
            logger.warning(f"LLM clustering failed: {e}")
            return None
    
    def cluster_entities(self, session_id: str) -> int:
        """Cluster entities in a session into concepts."""
        logger.info(f"Start clustering entities for session: {session_id}")
        
        # 1. Fetch all entities for this session.
        entities = self._get_session_entities(session_id)
        
        if len(entities) < self.min_cluster_size:
            logger.info(f"Not enough entities for clustering ({len(entities)} < {self.min_cluster_size})")
            return 0

        # 2. Call LLM for clustering (retry once if needed).
        clusters = self._llm_cluster_entities(session_id, entities)
        if clusters is None:
            clusters = self._llm_cluster_entities(session_id, entities)
        if not clusters:
            logger.info("LLM returned no valid clusters; skip")
            return 0

        # 3. Build content -> id mapping (first occurrence wins).
        content_to_id = {}
        for e in entities:
            c = (e.get("content") or "").strip()
            if c and c not in content_to_id:
                content_to_id[c] = e.get("id")

        # 4. For each cluster, create a Concept node and link members.
        concepts_created = 0
        for idx, cluster in enumerate(clusters):
            if concepts_created >= self.max_concepts:
                break
            if not isinstance(cluster, dict):
                continue
            name = (cluster.get("name") or "").strip()
            members = cluster.get("entities") or []
            if not name or not isinstance(members, list):
                continue

            # Filter out entities that are not present in the input list.
            member_ids = []
            member_entities = []
            for m in members:
                if not isinstance(m, str):
                    continue
                key = m.strip()
                if key in content_to_id and content_to_id[key]:
                    member_ids.append(content_to_id[key])
                    member_entities.append({"id": content_to_id[key], "content": key})

            # Respect minimum cluster size.
            if len(member_ids) < self.min_cluster_size:
                continue

            concept_id = self._create_concept_node_from_llm(session_id, name, member_entities)
            if concept_id:
                concepts_created += 1

        logger.info(f"Warm-layer clustering complete, created {concepts_created} concepts")
        return concepts_created

    def _get_session_entities(self, session_id: str) -> List[Dict]:
        """Get all entity nodes for a session."""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        MATCH (m)<-[:FROM_MESSAGE]-(e:Entity)
        WHERE e.layer = 0
        RETURN DISTINCT e.id as id, e.content as content, e.importance as importance
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def _create_concept_node_from_llm(self, session_id: str, concept_name: str, entities: List[Dict]) -> Optional[str]:
        """Create a Concept node from LLM output and link entities to it."""
        from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType
        import uuid
        
        concept_name = concept_name.strip()[:50]

        # Reuse an existing similar concept node when available.
        existing = self._find_similar_concept(session_id, concept_name)
        if existing:
            logger.debug(f"Reusing existing concept node: {existing}")
            # Link all entities to the reused concept.
            for entity in entities:
                self._link_entity_to_concept(entity['id'], existing)
            return existing
        
        # Create new concept node.
        concept_id = f"concept_{uuid.uuid4().hex[:12]}"
        concept_node = Neo4jNode(
            id=concept_id,
            type=NodeType.CONCEPT,
            content=concept_name,
            layer=1,  # warm layer
            importance=0.7,
            properties={
                "session_id": session_id,
                "entity_count": len(entities)
            }
        )
        
        self.connector.create_node(concept_node)
        logger.info(f"Created concept node (LLM): {concept_name} (entities={len(entities)})")
        
        # Link entities to concept node.
        for entity in entities:
            self._link_entity_to_concept(entity['id'], concept_id)
        
        # Link concept node back to session.
        session_relation = Neo4jRelation(
            type=RelationType.PART_OF_SESSION,
            source_id=concept_id,
            target_id=f"session_{session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return concept_id
    
    def _find_similar_concept(self, session_id: str, concept_name: str) -> Optional[str]:
        """Find an existing similar concept in the same session (simple substring match)."""
        query = """
        MATCH (c:Concept)
        WHERE c.session_id = $session_id AND c.content CONTAINS $keyword
        RETURN c.id as id
        LIMIT 1
        """
        
        keyword = concept_name.strip()[:12]
        
        if not keyword:
            return None
        
        results = self.connector.query(query, {"session_id": session_id, "keyword": keyword})
        return results[0]['id'] if results else None
    
    def _link_entity_to_concept(self, entity_id: str, concept_id: str):
        """Create BELONGS_TO relation from entity to concept."""
        from .models import Neo4jRelation, RelationType
        
        relation = Neo4jRelation(
            type=RelationType.BELONGS_TO,
            source_id=entity_id,
            target_id=concept_id,
            weight=0.8
        )
        self.connector.create_relation(relation)
    
    def get_concepts(self, session_id: str) -> List[Dict]:
        """Get all concept nodes for a session."""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(c:Concept)
        OPTIONAL MATCH (c)<-[:BELONGS_TO]-(e:Entity)
        RETURN c.id as id, c.content as content, c.importance as importance, 
               count(e) as entity_count
        ORDER BY c.importance DESC
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def get_entities_by_concept(self, concept_id: str) -> List[Dict]:
        """Get all entities that belong to a given concept."""
        query = """
        MATCH (c:Concept {id: $concept_id})<-[:BELONGS_TO]-(e:Entity)
        RETURN e.id as id, e.content as content, e.importance as importance
        ORDER BY e.importance DESC
        """
        
        results = self.connector.query(query, {"concept_id": concept_id})
        return [dict(r) for r in results]


def create_warm_layer_manager(connector):
    """
    Factory function to create a WarmLayerManager.

    Args:
        connector: Neo4j connector.

    Returns:
        WarmLayerManager instance, or None if memory is disabled.
    """
    try:
        from config import load_config
        config = load_config()
        
        # Check whether memory system is enabled.
        if not config.memory.enabled:
            logger.info("Memory system disabled")
            return None
        
        return WarmLayerManager(connector, config)
        
    except Exception as e:
        logger.warning(f"Warm-layer manager initialization failed: {e}")
        return None

