"""记忆遗忘机制"""

import math
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from .neo4j_connector import Neo4jConnector

logger = logging.getLogger(__name__)


class ForgettingManager:
    """记忆遗忘管理器"""
    
    def __init__(self, connector: Neo4jConnector):
        self.connector = connector
        
        # 遗忘曲线参数（天数 -> 衰减比例）
        self.decay_curve = {
            1: 1.0,      # 1天内：100%
            7: 0.9,      # 1周：90%
            30: 0.7,     # 1个月：70%
            90: 0.5,     # 3个月：50%
            365: 0.3,    # 1年：30%
            float('inf'): 0.2  # 1年后：20%（最低）
        }
        
        # 访问强化参数
        self.access_boost = 0.05  # 每次访问增加5%
        self.max_importance = 1.0
        
        # 清理阈值
        self.min_importance = 0.15  # 低于15%视为遗忘
        self.cleanup_batch = 100     # 每次清理100个节点
    
    def calculate_decay_factor(self, days_passed: float) -> float:
        """
        计算时间衰减因子
        
        Args:
            days_passed: 经过的天数
            
        Returns:
            衰减因子（0.2-1.0）
        """
        for threshold, factor in sorted(self.decay_curve.items()):
            if days_passed <= threshold:
                return factor
        return 0.2
    
    def apply_time_decay(self, session_id: str = None) -> Dict:
        """
        应用时间衰减到所有节点
        
        Args:
            session_id: 可选，只处理特定会话
            
        Returns:
            统计信息
        """
        try:
            # 构建查询
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
                WHERE n.layer IN [0, 1]  // 只衰减热层和温层
                AND n.created_at IS NOT NULL
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
            
            now = datetime.now()
            updated_count = 0
            
            for node in nodes:
                created_at = node['created_at']
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                
                # 计算天数差
                days_passed = (now - created_at).total_seconds() / 86400
                
                # 计算时间衰减
                decay_factor = self.calculate_decay_factor(days_passed)
                
                # 计算访问强化（每10次访问+5%，上限20%）
                access_count = node.get('access_count', 0)
                access_boost = min(0.2, (access_count // 10) * self.access_boost)
                
                # 原始重要性
                original_importance = node.get('importance', 0.5)
                
                # 新重要性 = 原始值 * 时间衰减 + 访问强化
                new_importance = min(
                    self.max_importance,
                    original_importance * decay_factor + access_boost
                )
                
                # 更新节点
                update_query = """
                MATCH (n {id: $id})
                SET n.importance = $importance
                """
                self.connector.query(update_query, {
                    'id': node['id'],
                    'importance': new_importance
                })
                
                updated_count += 1
            
            logger.info(f"时间衰减完成：更新了 {updated_count} 个节点")
            
            return {
                'updated_count': updated_count,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"时间衰减失败: {e}")
            return {
                'updated_count': 0,
                'status': 'error',
                'error': str(e)
            }
    
    def cleanup_forgotten(self, session_id: str = None) -> Dict:
        """
        清理遗忘的节点（importance < min_importance）
        
        Args:
            session_id: 可选，只清理特定会话
            
        Returns:
            统计信息
        """
        try:
            # 查找低importance节点
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
                WHERE n.layer = 0  // 只清理热层
                AND n.type <> 'Message'  // 保留原始消息
                AND n.importance < $min_importance
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
                AND n.type <> 'Message'
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
                # 删除节点及其关系
                delete_query = """
                MATCH (n {id: $id})
                DETACH DELETE n
                """
                self.connector.query(delete_query, {'id': node['id']})
                deleted_count += 1
            
            logger.info(f"清理遗忘节点：删除了 {deleted_count} 个节点")
            
            return {
                'deleted_count': deleted_count,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"清理遗忘节点失败: {e}")
            return {
                'deleted_count': 0,
                'status': 'error',
                'error': str(e)
            }
    
    def get_forgetting_stats(self, session_id: str = None) -> Dict:
        """
        获取遗忘统计信息
        
        Args:
            session_id: 可选，只统计特定会话
            
        Returns:
            统计信息
        """
        try:
            if session_id:
                query = """
                MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
                WHERE n.layer IN [0, 1]
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
            
            return {'status': 'no_data'}
            
        except Exception as e:
            logger.error(f"获取遗忘统计失败: {e}")
            return {'status': 'error', 'error': str(e)}


def create_forgetting_manager(connector: Neo4jConnector) -> ForgettingManager:
    """工厂函数"""
    return ForgettingManager(connector)

