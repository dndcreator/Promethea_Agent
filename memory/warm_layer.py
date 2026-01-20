"""
温层管理器
对热层节点进行语义聚类，生成主题概念节点
"""
import logging
import json
from typing import List, Dict, Optional
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
        
        # LLM 聚类参数
        self.min_cluster_size = config.memory.warm_layer.min_cluster_size
        self.max_concepts = getattr(config.memory.warm_layer, "max_concepts", 100)
        self.cluster_model = getattr(config.api, "model", "")
        
        logger.info("温层管理器初始化完成")
    
    def _extract_json(self, text: str) -> Optional[dict]:
        """尽量从模型输出中提取 JSON（允许 ```json 包裹）。"""
        if not text:
            return None
        s = text.strip()
        if "```json" in s:
            try:
                s = s.split("```json", 1)[1].split("```", 1)[0].strip()
            except Exception:
                pass
        elif "```" in s:
            # 有些模型会用 ``` 包裹但不写 json
            try:
                s = s.split("```", 1)[1].split("```", 1)[0].strip()
            except Exception:
                pass

        # 截取最外层对象
        if "{" in s and "}" in s:
            s = s[s.find("{"): s.rfind("}") + 1]
        try:
            return json.loads(s)
        except Exception:
            return None

    def _llm_cluster_entities(self, session_id: str, entities: List[Dict]) -> Optional[List[Dict]]:
        """
        让 LLM 将实体聚类为概念簇。

        Returns:
            clusters: [{ "name": str, "entities": [str] }]
        """
        # 只给模型看必要字段，避免 prompt 过长
        entity_names = [e.get("content", "") for e in entities if e.get("content")]
        entity_names = list(dict.fromkeys(entity_names))  # 去重保序

        prompt = f"""你是一个信息组织助手。请把下面的“实体列表”聚成若干个“概念/主题簇”。
要求：
1) 输出必须是严格 JSON（不要额外文字）。
2) JSON 格式：{{"clusters":[{{"name":"概念名","entities":["实体1","实体2"]}}], "unassigned":["无法归类的实体"]}}
3) clusters 数量不要太多（<= {min(12, max(3, self.max_concepts))}），每个 clusters 至少包含 {self.min_cluster_size} 个实体；实体必须来自输入列表。
4) 概念名用中文、短一些（<= 12 字），尽量抽象（如“工作项目/技术栈/家庭安排/健康作息”等）。
5) 不要编造不存在的实体。

会话ID：{session_id}
实体列表（共 {len(entity_names)} 个）：
{json.dumps(entity_names, ensure_ascii=False)}
"""
        messages = [
            {"role": "system", "content": "你擅长把零散实体归纳成少量主题簇，并输出严格 JSON。"},
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
            logger.warning(f"LLM 聚类失败: {e}")
            return None
    
    def cluster_entities(self, session_id: str) -> int:
        """
        对会话中的实体节点进行聚类
        """
        logger.info(f"开始对会话 {session_id} 的实体进行聚类")
        
        # 1. 获取所有实体节点
        entities = self._get_session_entities(session_id)
        
        if len(entities) < self.min_cluster_size:
            logger.info(f"实体数量不足 ({len(entities)} < {self.min_cluster_size})，跳过聚类")
            return 0

        # 2. 调用 LLM 聚类（必要时重试一次）
        clusters = self._llm_cluster_entities(session_id, entities)
        if clusters is None:
            clusters = self._llm_cluster_entities(session_id, entities)
        if not clusters:
            logger.info("LLM 未返回有效聚类结果，跳过")
            return 0

        # 3. 建立 content -> id 映射（同名取第一个）
        content_to_id = {}
        for e in entities:
            c = (e.get("content") or "").strip()
            if c and c not in content_to_id:
                content_to_id[c] = e.get("id")

        # 4. 为每个聚类创建 Concept 节点并建立关系
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

            # 过滤掉不在输入列表的实体
            member_ids = []
            member_entities = []
            for m in members:
                if not isinstance(m, str):
                    continue
                key = m.strip()
                if key in content_to_id and content_to_id[key]:
                    member_ids.append(content_to_id[key])
                    member_entities.append({"id": content_to_id[key], "content": key})

            # 最小簇大小约束
            if len(member_ids) < self.min_cluster_size:
                continue

            concept_id = self._create_concept_node_from_llm(session_id, name, member_entities)
            if concept_id:
                concepts_created += 1

        logger.info(f"LLM 温层聚类完成，创建了 {concepts_created} 个概念节点")
        return concepts_created

    def _get_session_entities(self, session_id: str) -> List[Dict]:
        """获取会话的所有实体节点"""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        MATCH (m)<-[:FROM_MESSAGE]-(e:Entity)
        WHERE e.layer = 0
        RETURN DISTINCT e.id as id, e.content as content, e.importance as importance
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def _create_concept_node_from_llm(self, session_id: str, concept_name: str, entities: List[Dict]) -> Optional[str]:
        """根据 LLM 给出的 concept_name + 实体列表创建概念节点并建立关系。"""
        from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType
        import uuid
        
        concept_name = concept_name.strip()[:50]

        # 检查是否已存在相似概念（限定在会话内）
        existing = self._find_similar_concept(session_id, concept_name)
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
            importance=0.7,
            properties={
                "session_id": session_id,
                "entity_count": len(entities)
            }
        )
        
        self.connector.create_node(concept_node)
        logger.info(f"创建概念节点(LLM): {concept_name} (包含 {len(entities)} 个实体)")
        
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
    
    def _find_similar_concept(self, session_id: str, concept_name: str) -> Optional[str]:
        """查找相似的概念节点（限定会话，简单字符串匹配）"""
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

