"""
温层管理器
对热层节点进行语义聚类，生成主题概念节点
"""
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize
from openai import OpenAI

logger = logging.getLogger(__name__)


class WarmLayerManager:
    """温层记忆管理器 - 语义聚类"""
    
    def __init__(self, connector, config):
        """
        初始化温层管理器
        
        Args:
            connector: Neo4j 连接器
            config: 配置对象
        """
        self.connector = connector
        self.config = config
        
        # 初始化 Embedding 客户端
        self.client = OpenAI(
            api_key=config.api.api_key,
            base_url=config.api.base_url
        )
        
        # 聚类参数
        self.clustering_threshold = config.memory.warm_layer.clustering_threshold
        self.min_cluster_size = config.memory.warm_layer.min_cluster_size
        
        logger.info("温层管理器初始化完成")
    
    def get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        获取文本的 Embedding 向量
        
        Args:
            text: 输入文本
            
        Returns:
            向量数组，失败返回 None
        """
        try:
            # 截断过长文本
            text = text[:500]
            
            # 调用 Embedding API（使用 text-embedding-3-small 模型）
            response = self.client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
                encoding_format="float"
            )
            
            embedding = response.data[0].embedding
            return np.array(embedding)
            
        except Exception as e:
            logger.warning(f"获取 Embedding 失败: {e}")
            return None
    
    def cluster_entities(self, session_id: str) -> int:
        """
        对会话中的实体节点进行聚类
        """
        logger.info(f"开始对会话 {session_id} 的实体进行聚类")
        
        # 1. 获取所有实体节点（包含已有的 embedding）
        entities = self._get_session_entities(session_id)
        
        if len(entities) < self.min_cluster_size:
            logger.info(f"实体数量不足 ({len(entities)} < {self.min_cluster_size})，跳过聚类")
            return 0
        
        # 2. 获取 Embeddings（优先使用缓存）
        entity_embeddings = []
        valid_entities = []
        new_embeddings_count = 0
        
        for entity in entities:
            embedding = entity.get('embedding')
            
            # 如果缓存中有 embedding，直接使用
            if embedding:
                # Neo4j 返回的可能是列表，转为 numpy array
                embedding = np.array(embedding)
            else:
                # 缓存未命中，调用 API
                embedding = self.get_embedding(entity['content'])
                if embedding is not None:
                    # 立即缓存回 Neo4j，避免下次重复计算
                    self._save_embedding(entity['id'], embedding.tolist())
                    new_embeddings_count += 1
            
            if embedding is not None:
                entity_embeddings.append(embedding)
                valid_entities.append(entity)
        
        if new_embeddings_count > 0:
            logger.info(f"新计算并缓存了 {new_embeddings_count} 个 Embeddings")
        
        if len(entity_embeddings) < self.min_cluster_size:
            logger.info("有效 Embedding 不足，跳过聚类")
            return 0
        
        # 3. 归一化向量
        embeddings_matrix = np.array(entity_embeddings)
        embeddings_normalized = normalize(embeddings_matrix)
        
        # 4. DBSCAN 聚类（基于余弦相似度）
        eps = 1 - self.clustering_threshold
        clustering = DBSCAN(
            eps=eps,
            min_samples=self.min_cluster_size,
            metric='cosine'
        ).fit(embeddings_normalized)
        
        labels = clustering.labels_
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        
        logger.info(f"聚类完成: {n_clusters} 个主题, {sum(labels == -1)} 个噪声点")
        
        # 5. 为每个聚类创建 Concept 节点
        concepts_created = 0
        for cluster_id in set(labels):
            if cluster_id == -1:  # 跳过噪声点
                continue
            
            cluster_entities = [valid_entities[i] for i, label in enumerate(labels) if label == cluster_id]
            concept_id = self._create_concept_node(session_id, cluster_id, cluster_entities)
            
            if concept_id:
                concepts_created += 1
        
        logger.info(f"创建了 {concepts_created} 个概念节点")
        return concepts_created
    
    def _save_embedding(self, entity_id: str, embedding: List[float]):
        """将 Embedding 保存到节点属性中"""
        query = """
        MATCH (e {id: $id})
        SET e.embedding = $embedding
        """
        self.connector.query(query, {"id": entity_id, "embedding": embedding})

    def _get_session_entities(self, session_id: str) -> List[Dict]:
        """获取会话的所有实体节点"""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        MATCH (m)<-[:FROM_MESSAGE]-(e:Entity)
        WHERE e.layer = 0
        RETURN DISTINCT e.id as id, e.content as content, e.importance as importance, e.embedding as embedding
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def _create_concept_node(self, session_id: str, cluster_id: int, entities: List[Dict]) -> Optional[str]:
        """
        创建概念节点
        
        Args:
            session_id: 会话ID
            cluster_id: 聚类ID
            entities: 聚类中的实体列表
            
        Returns:
            概念节点ID
        """
        from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType
        import uuid
        
        # 生成概念名称（使用最重要的实体）
        entities_sorted = sorted(entities, key=lambda e: e.get('importance', 0.5), reverse=True)
        top_entities = [e['content'] for e in entities_sorted[:3]]
        concept_name = f"主题: {', '.join(top_entities)}"
        
        # 检查是否已存在相似概念
        existing = self._find_similar_concept(concept_name)
        if existing:
            logger.debug(f"概念已存在: {existing}")
            # 直接建立关系
            for entity in entities:
                self._link_entity_to_concept(entity['id'], existing)
            return existing
        
        # 创建新概念节点
        concept_id = f"concept_{uuid.uuid4().hex[:12]}"
        concept_node = Neo4jNode(
            id=concept_id,
            type=NodeType.CONCEPT,
            content=concept_name,
            layer=1,  # 温层
            importance=np.mean([e.get('importance', 0.5) for e in entities]),
            properties={
                "session_id": session_id,
                "cluster_id": cluster_id,
                "entity_count": len(entities)
            }
        )
        
        self.connector.create_node(concept_node)
        logger.info(f"创建概念节点: {concept_name} (包含 {len(entities)} 个实体)")
        
        # 建立实体到概念的关系
        for entity in entities:
            self._link_entity_to_concept(entity['id'], concept_id)
        
        # 连接到会话
        session_relation = Neo4jRelation(
            type=RelationType.PART_OF_SESSION,
            source_id=concept_id,
            target_id=f"session_{session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return concept_id
    
    def _find_similar_concept(self, concept_name: str) -> Optional[str]:
        """查找相似的概念节点（简单字符串匹配）"""
        query = """
        MATCH (c:Concept)
        WHERE c.content CONTAINS $keyword
        RETURN c.id as id
        LIMIT 1
        """
        
        # 提取关键词（简单实现：取第一个实体名）
        keyword = concept_name.split(':')[1].split(',')[0].strip() if ':' in concept_name else ""
        
        if not keyword:
            return None
        
        results = self.connector.query(query, {"keyword": keyword})
        return results[0]['id'] if results else None
    
    def _link_entity_to_concept(self, entity_id: str, concept_id: str):
        """建立实体到概念的关系"""
        from .models import Neo4jRelation, RelationType
        
        relation = Neo4jRelation(
            type=RelationType.BELONGS_TO,
            source_id=entity_id,
            target_id=concept_id,
            weight=0.8
        )
        self.connector.create_relation(relation)
    
    def get_concepts(self, session_id: str) -> List[Dict]:
        """获取会话的所有概念"""
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
        """获取概念下的所有实体"""
        query = """
        MATCH (c:Concept {id: $concept_id})<-[:BELONGS_TO]-(e:Entity)
        RETURN e.id as id, e.content as content, e.importance as importance
        ORDER BY e.importance DESC
        """
        
        results = self.connector.query(query, {"concept_id": concept_id})
        return [dict(r) for r in results]


def create_warm_layer_manager(connector):
    """
    工厂函数：创建温层管理器
    
    Args:
        connector: Neo4j 连接器
        
    Returns:
        WarmLayerManager 实例，失败返回 None
    """
    try:
        from config import load_config
        config = load_config()
        
        # 检查是否启用
        if not config.memory.enabled:
            logger.info("记忆系统未启用")
            return None
        
        return WarmLayerManager(connector, config)
        
    except Exception as e:
        logger.warning(f"温层管理器初始化失败: {e}")
        return None

