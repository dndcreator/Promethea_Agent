"""自动记忆召回引擎"""

from typing import List, Dict
from datetime import datetime
from .neo4j_connector import Neo4jConnector
from .llm_extractor import LLMExtractor
import logging

logger = logging.getLogger(__name__)


class AutoRecallEngine:
    """基于图谱的自动记忆召回（动态参数）"""
    
    def __init__(self, connector: Neo4jConnector, extractor: LLMExtractor):
        self.connector = connector
        self.extractor = extractor
    
    def recall(self, query: str, session_id: str, user_id: str = "default_user") -> str:
        """召回相关记忆并格式化为上下文"""
        try:
            # 提取查询实体
            extraction = self.extractor.extract(role="user", content=query)
            entities = extraction.entities if extraction.entities else []
            
            # 动态计算参数
            params = self._calculate_params(query, entities)
            
            # 三层查询 (传入 user_id)
            results = self._three_layer_query(entities, session_id, user_id, params['recent_days'])
            
            # 格式化
            return self._format_context(results, params['max_tokens'], params['items_per_layer'])
            
        except Exception as e:
            logger.error(f"记忆召回失败: {e}")
            return ""
    
    def _calculate_params(self, query: str, entities: List[str]) -> Dict:
        """根据查询特征动态计算参数"""
        entity_count = len(entities)
        query_length = len(query)
        
        # 简单分级
        if entity_count >= 3 or query_length > 80:
            level = 'complex'
        elif entity_count >= 1 or query_length > 20:
            level = 'normal'
        else:
            level = 'simple'
        
        # 参数预设
        presets = {
            'simple':  {'max_tokens': 800,  'items_per_layer': 2, 'recent_days': 3},
            'normal':  {'max_tokens': 1500, 'items_per_layer': 3, 'recent_days': 7},
            'complex': {'max_tokens': 2500, 'items_per_layer': 5, 'recent_days': 14}
        }
        
        params = presets[level]
        
        # 回忆型问题特殊处理
        if any(kw in query for kw in ["之前", "刚才", "上次", "记得", "说过"]):
            params['items_per_layer'] += 1
            params['recent_days'] += 3
        
        return params
    
    def _three_layer_query(self, entities: List[str], session_id: str, user_id: str, recent_days: int = 7) -> Dict:
        """三层并行查询 (支持跨会话的用户级召回)"""
        
        # 重要：查询必须匹配当前图谱schema
        # - User 节点 id 使用 "user_{user_id}"
        # - Session 节点 id 使用 "session_{session_id}"
        # - Session 属于 User: (:Session)-[:OWNED_BY]->(:User)
        # - Message 属于 Session: (:Message)-[:PART_OF_SESSION]->(:Session)
        
        cypher = """
        // 查找用户节点
        WITH $entities AS query_entities, $user_node_id AS uid, $session_node_id as current_sid
        
        // Layer 1: 实体直连 (跨会话，但限制为该用户的会话)
        // 路径: Entity -> Message -> Session -> User
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

        // Layer 2: 图谱扩散 (跨会话)
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

        // Layer 3: 近期窗口 (仅限当前会话，保持上下文连贯性)
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
                    "user_node_id": f"user_{user_id}",
                    "session_node_id": f"session_{session_id}",
                    "recent_days": recent_days
                }
            )
            
            return result[0]['results'] if result else {
                'direct': [], 'related': [], 'recent': []
            }
        except Exception as e:
            logger.error(f"图谱查询失败: {e}")
            return {'direct': [], 'related': [], 'recent': []}
    
    def _format_context(self, results: Dict, max_tokens: int = 1500, items_per_layer: int = 3) -> str:
        """格式化上下文"""
        lines = []
        token_count = 0
        
        # 按优先级处理
        priorities = [
            ('direct', results.get('direct', []), '【直接相关记忆】'),
            ('related', results.get('related', []), '【关联知识】'),
            ('recent', results.get('recent', []), '【近期对话】')
        ]
        
        for layer_name, items, header in priorities:
            if not items:
                continue
            
            # 排序
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
                
                # Token限制
                est_tokens = len(content) // 1.5
                if token_count + est_tokens > max_tokens:
                    break
                
                # 格式化
                t = item.get('time')
                # Neo4j driver 可能返回 neo4j.time.DateTime；这里做最稳妥的字符串化
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
                
                via_str = f" (关联: {item['via']})" if item.get('via') else ""
                # 如果是跨会话的记忆，可以标注来源（可选）
                # session_str = f" [Session: {item.get('session_id')}]" if item.get('session_id') else ""
                
                layer_lines.append(f"- [{time_str}] {content[:100]}...{via_str}")
                token_count += est_tokens
            
            if len(layer_lines) > 1:
                lines.extend(layer_lines)
                lines.append("")
        
        return "\n".join(lines) if lines else ""
