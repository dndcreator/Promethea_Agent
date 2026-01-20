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
    
    def recall(self, query: str, session_id: str) -> str:
        """召回相关记忆并格式化为上下文"""
        try:
            # 提取查询实体
            extraction = self.extractor.extract(role="user", content=query)
            entities = extraction.entities if extraction.entities else []
            
            # 动态计算参数
            params = self._calculate_params(query, entities)
            
            # 三层查询
            results = self._three_layer_query(entities, session_id, params['recent_days'])
            
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
    
    def _three_layer_query(self, entities: List[str], session_id: str, recent_days: int = 7) -> Dict:
        """三层并行查询"""
        
        # 重要：查询必须匹配当前图谱schema
        # - Session 节点 id 使用 "session_{session_id}"
        # - Message 节点通过 (:Message)-[:PART_OF_SESSION]->(:Session) 归属会话
        # - Entity/Action/Time/Location 通过 (:X)-[:FROM_MESSAGE]->(:Message) 关联消息
        # - Entity 与 Action 通过 SUBJECT_OF / OBJECT_OF 关联
        cypher = """
        // Layer 1: 实体直连（实体 -> FROM_MESSAGE -> 消息 -> PART_OF_SESSION -> 会话）
        WITH $entities AS query_entities, $session_node_id AS sid
        OPTIONAL MATCH (s:Session {id: sid})
        OPTIONAL MATCH (e:Entity)
        WHERE e.content IN query_entities
        OPTIONAL MATCH (e)-[:FROM_MESSAGE]->(direct_msg:Message)-[:PART_OF_SESSION]->(s)
        WITH collect(DISTINCT {
            content: direct_msg.content,
            time: direct_msg.created_at,
            importance: direct_msg.importance,
            layer: 'direct'
        }) AS layer1_results, sid

        // Layer 2: 图谱扩散（实体 <-> 动作 <-> 相关实体，再取相关实体关联的消息）
        OPTIONAL MATCH (s:Session {id: sid})
        OPTIONAL MATCH (e0:Entity)
        WHERE e0.content IN $entities
        OPTIONAL MATCH (e0)-[:SUBJECT_OF|OBJECT_OF]-(a:Action)-[:SUBJECT_OF|OBJECT_OF]-(related:Entity)
        WHERE related.content IS NOT NULL AND related.content <> e0.content
        OPTIONAL MATCH (related)-[:FROM_MESSAGE]->(related_msg:Message)-[:PART_OF_SESSION]->(s)
        WITH layer1_results, collect(DISTINCT {
            content: related_msg.content,
            time: related_msg.created_at,
            importance: related_msg.importance,
            layer: 'related',
            via: related.content
        }) AS layer2_results, sid

        // Layer 3: 近期窗口（会话内最近消息）
        OPTIONAL MATCH (s:Session {id: sid})
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
            ('direct', results.get('direct', []), '【直接相关】'),
            ('related', results.get('related', []), '【关联信息】'),
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
                
                layer_lines.append(f"- [{time_str}] {content[:100]}...{via_str}")
                token_count += est_tokens
            
            if len(layer_lines) > 1:
                lines.extend(layer_lines)
                lines.append("")
        
        return "\n".join(lines) if lines else ""

