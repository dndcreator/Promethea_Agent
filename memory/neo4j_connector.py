"""
Neo4j 数据库连接器
"""
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, Transaction
from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType

logger = logging.getLogger(__name__)


class Neo4jConnector:
    """Neo4j 图数据库连接器"""
    
    def __init__(self, config):
        """
        初始化连接器
        
        Args:
            config: Neo4j 配置
        """
        self.config = config
        self.driver = GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
            max_connection_lifetime=config.max_connection_lifetime,
            max_connection_pool_size=config.max_connection_pool_size,
            connection_timeout=config.connection_timeout
        )
        self._create_constraints()
        logger.info(f"Neo4j 连接器初始化完成: {config.uri}")
    
    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j 连接已关闭")
    
    def _create_constraints(self):
        """创建必要的约束和索引"""
        with self.driver.session(database=self.config.database) as session:
            # 为每种节点类型创建唯一性约束（如果不存在）
            constraints = [
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT action_id IF NOT EXISTS FOR (n:Action) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT message_id IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (n:Session) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT time_id IF NOT EXISTS FOR (n:Time) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT location_id IF NOT EXISTS FOR (n:Location) REQUIRE n.id IS UNIQUE",
            ]
            
            # 为 content 字段创建索引，用于快速查重
            indexes = [
                # 内容查重索引（核心）
                "CREATE INDEX entity_content IF NOT EXISTS FOR (n:Entity) ON (n.content)",
                "CREATE INDEX action_content IF NOT EXISTS FOR (n:Action) ON (n.content)",
                "CREATE INDEX time_content IF NOT EXISTS FOR (n:Time) ON (n.content)",
                "CREATE INDEX location_content IF NOT EXISTS FOR (n:Location) ON (n.content)",
                
                # 会话查询索引
                "CREATE INDEX message_session IF NOT EXISTS FOR (n:Message) ON (n.properties.session_id)",
                
                # 时间查询索引
                "CREATE INDEX message_created IF NOT EXISTS FOR (n:Message) ON (n.created_at)",
                
                # 重要性查询索引
                "CREATE INDEX node_importance IF NOT EXISTS FOR (n:Entity) ON (n.importance)",
                "CREATE INDEX node_layer IF NOT EXISTS FOR (n) ON (n.layer)",
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"约束创建跳过或失败: {e}")
            
            for index in indexes:
                try:
                    session.run(index)
                    logger.debug(f"索引创建成功: {index.split()[2]}")
                except Exception as e:
                    logger.debug(f"索引创建跳过或失败: {e}")
    
    def create_node(self, node: Neo4jNode) -> str:
        """
        创建节点
        
        Args:
            node: 节点对象
            
        Returns:
            节点的 Neo4j ID
        """
        with self.driver.session(database=self.config.database) as session:
            result = session.execute_write(self._create_node_tx, node)
            return result
    
    @staticmethod
    def _create_node_tx(tx: Transaction, node: Neo4jNode) -> str:
        """创建节点的事务"""
        # 生成节点 ID（如果没有）
        if not node.id:
            import uuid
            node.id = f"{node.type.value.lower()}_{uuid.uuid4().hex[:12]}"
        
        # 构建 Cypher 查询
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
            properties=node.properties
        )
        
        record = result.single()
        return record["id"] if record else node.id
    
    def create_relation(self, relation: Neo4jRelation) -> bool:
        """
        创建关系
        
        Args:
            relation: 关系对象
            
        Returns:
            是否成功
        """
        with self.driver.session(database=self.config.database) as session:
            return session.execute_write(self._create_relation_tx, relation)
    
    @staticmethod
    def _create_relation_tx(tx: Transaction, relation: Neo4jRelation) -> bool:
        """创建关系的事务"""
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
                properties=relation.properties
            )
            return result.single() is not None
        except Exception as e:
            logger.error(f"创建关系失败: {e}")
            return False
    
    def query(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行 Cypher 查询
        
        Args:
            cypher: Cypher 查询语句
            parameters: 查询参数
            
        Returns:
            查询结果列表
        """
        with self.driver.session(database=self.config.database) as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取节点"""
        query = "MATCH (n {id: $id}) RETURN n"
        results = self.query(query, {"id": node_id})
        return results[0]["n"] if results else None
    
    def find_node_by_content(self, node_type: NodeType, content: str) -> Optional[str]:
        """
        根据类型和内容查找已存在的节点
        
        Args:
            node_type: 节点类型
            content: 节点内容
            
        Returns:
            节点ID（如果存在）
        """
        query = f"MATCH (n:{node_type.value} {{content: $content}}) RETURN n.id as id LIMIT 1"
        results = self.query(query, {"content": content})
        return results[0]["id"] if results else None
    
    def get_neighbors(self, node_id: str, relation_type: Optional[RelationType] = None, 
                     direction: str = "both") -> List[Dict[str, Any]]:
        """
        获取邻居节点
        
        Args:
            node_id: 节点ID
            relation_type: 关系类型（可选）
            direction: 方向 (in/out/both)
            
        Returns:
            邻居节点列表
        """
        rel_pattern = f":{relation_type.value}" if relation_type else ""
        
        if direction == "out":
            pattern = f"(n {{id: $id}})-[r{rel_pattern}]->(m)"
        elif direction == "in":
            pattern = f"(n {{id: $id}})<-[r{rel_pattern}]-(m)"
        else:
            pattern = f"(n {{id: $id}})-[r{rel_pattern}]-(m)"
        
        query = f"MATCH {pattern} RETURN m, r"
        results = self.query(query, {"id": node_id})
        
        return [{"node": r["m"], "relation": r["r"]} for r in results]
    
    def delete_node(self, node_id: str) -> bool:
        """删除节点及其关系"""
        query = "MATCH (n {id: $id}) DETACH DELETE n"
        try:
            self.query(query, {"id": node_id})
            return True
        except Exception as e:
            logger.error(f"删除节点失败: {e}")
            return False
    
    def clear_database(self):
        """清空数据库（危险操作！）"""
        query = "MATCH (n) DETACH DELETE n"
        self.query(query)
        logger.warning("数据库已清空")
    
    def show_indexes(self) -> List[Dict[str, Any]]:
        """显示所有索引状态"""
        query = "SHOW INDEXES"
        return self.query(query)
    
    def get_statistics(self) -> Dict[str, int]:
        """获取数据库统计信息"""
        query = """
        MATCH (n)
        RETURN labels(n)[0] as type, count(n) as count
        """
        results = self.query(query)
        stats = {r["type"]: r["count"] for r in results if r["type"]}
        
        # 获取关系数量
        rel_query = "MATCH ()-[r]->() RETURN count(r) as rel_count"
        rel_result = self.query(rel_query)
        stats["_relationships"] = rel_result[0]["rel_count"] if rel_result else 0
        
        return stats


class Neo4jConnectionPool:
    """Neo4j 连接池管理器（单例模式）"""
    
    _instance = None
    _connector = None
    
    @classmethod
    def get_connector(cls, config = None):
        """获取连接器实例"""
        if cls._connector is None:
            if config is None:
                from config import load_config
                main_config = load_config()
                config = main_config.memory.neo4j
            cls._connector = Neo4jConnector(config)
        return cls._connector
    
    @classmethod
    def close(cls):
        """关闭连接"""
        if cls._connector:
            cls._connector.close()
            cls._connector = None


