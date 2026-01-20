"""
冷层管理器
对会话记忆进行 LLM 摘要压缩，生成长期记忆
"""
import logging
from typing import List, Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class ColdLayerManager:
    """冷层记忆管理器 - LLM 摘要压缩"""
    
    def __init__(self, connector, config):
        """
        初始化冷层管理器
        
        Args:
            connector: Neo4j 连接器
            config: 配置对象
        """
        self.connector = connector
        self.config = config
        
        # 初始化 LLM 客户端
        self.client = OpenAI(
            api_key=config.api.api_key,
            base_url=config.api.base_url
        )
        
        # 摘要参数
        # 优先使用冷层配置的摘要模型（允许与对话模型不同）
        self.summary_model = getattr(config.memory.cold_layer, "summary_model", None) or config.api.model
        self.max_summary_length = config.memory.cold_layer.max_summary_length
        self.compression_threshold = config.memory.cold_layer.compression_threshold
        
        logger.info("冷层管理器初始化完成")
    
    def summarize_session(self, session_id: str, include_concepts: bool = True) -> Optional[str]:
        """
        对会话生成摘要
        
        Args:
            session_id: 会话ID
            include_concepts: 是否包含温层概念信息
            
        Returns:
            摘要节点ID，失败返回 None
        """
        logger.info(f"开始为会话 {session_id} 生成摘要")
        
        # 1. 收集会话内容
        messages = self._get_session_messages(session_id)
        
        if len(messages) < 5:
            logger.info(f"消息数量不足 ({len(messages)} < 5)，跳过摘要")
            return None
        
        # 2. 可选：获取概念信息
        concepts = []
        if include_concepts:
            concepts = self._get_session_concepts(session_id)
        
        # 3. 调用 LLM 生成摘要
        summary_text = self._generate_summary(messages, concepts)
        
        if not summary_text:
            logger.warning("摘要生成失败")
            return None
        
        # 4. 创建摘要节点
        summary_id = self._create_summary_node(session_id, summary_text, len(messages))
        
        logger.info(f"摘要生成完成: {summary_id}")
        return summary_id
    
    def _get_session_messages(self, session_id: str, skip: int = 0) -> List[Dict]:
        """
        获取会话的消息
        
        Args:
            session_id: 会话ID
            skip: 跳过前N条消息（用于增量获取）
        """
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        WHERE m.layer = 0
        RETURN m.content as content, m.role as role, m.created_at as created_at
        ORDER BY m.created_at ASC
        SKIP $skip
        """
        
        results = self.connector.query(query, {
            "session_id": f"session_{session_id}",
            "skip": skip
        })
        return [dict(r) for r in results]
    
    def _get_session_concepts(self, session_id: str) -> List[str]:
        """获取会话的概念（来自温层）"""
        query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(c:Concept)
        RETURN c.content as content
        ORDER BY c.importance DESC
        LIMIT 10
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [r['content'] for r in results]
    
    def _generate_summary(self, messages: List[Dict], concepts: List[str]) -> Optional[str]:
        """
        使用 LLM 生成摘要
        
        Args:
            messages: 消息列表
            concepts: 概念列表（可选）
            
        Returns:
            摘要文本
        """
        # 构建对话历史文本
        conversation_text = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in messages
        ])
        
        # 构建 prompt
        prompt = f"""请为以下对话生成一个简洁的摘要，重点突出：
1. 对话的主要话题和内容
2. 用户的关键需求或问题
3. 重要的信息和结论

对话内容：
{conversation_text}
"""
        
        # 如果有概念信息，加入 prompt
        if concepts:
            concepts_text = "、".join(concepts)
            prompt += f"\n\n识别到的主题：{concepts_text}\n"
        
        prompt += f"\n请用 {self.max_summary_length} 字以内生成摘要："
        
        try:
            # 调用 LLM
            response = self.client.chat.completions.create(
                model=self.summary_model,
                messages=[
                    {"role": "system", "content": "你是一个专业的对话摘要助手，擅长提炼对话的核心内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # 较低温度，保持摘要稳定
                max_tokens=self.max_summary_length * 2  # 留足空间
            )
            
            summary = response.choices[0].message.content.strip()
            logger.info(f"摘要生成成功，长度: {len(summary)} 字符")
            return summary
            
        except Exception as e:
            logger.error(f"LLM 摘要生成失败: {e}")
            return None
    
    def _create_summary_node(self, session_id: str, summary_text: str, message_count: int) -> Optional[str]:
        """
        创建摘要节点
        
        Args:
            session_id: 会话ID
            summary_text: 摘要内容
            message_count: 原始消息数量
            
        Returns:
            摘要节点ID
        """
        from .models import Neo4jNode, Neo4jRelation, NodeType, RelationType
        import uuid
        from datetime import datetime
        
        # 创建摘要节点
        summary_id = f"summary_{uuid.uuid4().hex[:12]}"
        summary_node = Neo4jNode(
            id=summary_id,
            type=NodeType.SUMMARY,
            content=summary_text,
            layer=2,  # 冷层
            importance=0.9,  # 摘要通常很重要
            properties={
                "session_id": session_id,
                "message_count": message_count,
            }
        )
        
        self.connector.create_node(summary_node)
        logger.info(f"创建摘要节点: {summary_id}")
        
        # 连接到会话
        session_relation = Neo4jRelation(
            type=RelationType.SUMMARIZES,
            source_id=summary_id,
            target_id=f"session_{session_id}",
            weight=1.0
        )
        self.connector.create_relation(session_relation)
        
        return summary_id
    
    def get_summaries(self, session_id: str) -> List[Dict]:
        """获取会话的所有摘要"""
        query = """
        MATCH (s:Session {id: $session_id})<-[:SUMMARIZES]-(sum:Summary)
        RETURN sum.id as id, sum.content as content, 
               sum.importance as importance, 
               sum.message_count as message_count,
               sum.created_at as created_at
        ORDER BY sum.created_at DESC
        """
        
        results = self.connector.query(query, {"session_id": f"session_{session_id}"})
        return [dict(r) for r in results]
    
    def get_summary_by_id(self, summary_id: str) -> Optional[Dict]:
        """获取特定摘要"""
        query = """
        MATCH (sum:Summary {id: $summary_id})
        RETURN sum.id as id, sum.content as content, 
               sum.importance as importance,
               sum.properties as properties
        """
        
        results = self.connector.query(query, {"summary_id": summary_id})
        return dict(results[0]) if results else None
    
    def should_create_summary(self, session_id: str) -> bool:
        """
        判断是否应该创建摘要
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否应该创建摘要
        """
        # 检查消息数量
        messages = self._get_session_messages(session_id)
        
        if len(messages) < self.compression_threshold:
            return False
        
        # 检查是否已有最近的摘要
        summaries = self.get_summaries(session_id)
        if summaries:
            # 如果最近有摘要，计算新增消息数
            latest_summary = summaries[0]
            summarized_count = latest_summary.get('message_count', 0)
            new_messages = len(messages) - summarized_count
            
            # 如果新消息少于阈值的一半，不创建
            if new_messages < self.compression_threshold // 2:
                return False
        
        return True
    
    def create_incremental_summary(self, session_id: str) -> Optional[str]:
        """
        创建增量摘要（只摘要新增的消息）
        
        Args:
            session_id: 会话ID
            
        Returns:
            摘要节点ID
        """
        logger.info(f"为会话 {session_id} 创建增量摘要")
        
        # 获取上一次摘要
        summaries = self.get_summaries(session_id)
        
        if not summaries:
            # 没有历史摘要，创建完整摘要
            # 此时 skip=0，获取所有消息
            return self.summarize_session(session_id)
        
        # 计算已摘要的消息数
        latest_summary = summaries[0]
        summarized_count = latest_summary.get('message_count', 0)
        
        # 只获取新增的消息（使用 SKIP 优化性能）
        new_messages = self._get_session_messages(session_id, skip=summarized_count)
        
        if len(new_messages) < 5:
            logger.info("新增消息不足，跳过增量摘要")
            return None
        
        # 生成增量摘要（包含上一次摘要作为上下文）
        previous_summary = latest_summary['content']
        incremental_summary = self._generate_incremental_summary(
            previous_summary, 
            new_messages
        )
        
        if not incremental_summary:
            return None
        
        # 创建摘要节点
        # 新的总数 = 旧的总数 + 新增数
        total_count = summarized_count + len(new_messages)
        summary_id = self._create_summary_node(
            session_id, 
            incremental_summary,
            total_count
        )
        
        return summary_id
    
    def _generate_incremental_summary(self, previous_summary: str, new_messages: List[Dict]) -> Optional[str]:
        """生成增量摘要"""
        conversation_text = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in new_messages
        ])
        
        prompt = f"""之前的对话摘要：
{previous_summary}

新增的对话内容：
{conversation_text}

请在之前摘要的基础上，整合新内容，生成一个更新的摘要（{self.max_summary_length} 字以内）：
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.summary_model,
                messages=[
                    {"role": "system", "content": "你是一个专业的对话摘要助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=self.max_summary_length * 2
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"增量摘要生成失败: {e}")
            return None


def create_cold_layer_manager(connector):
    """
    工厂函数：创建冷层管理器
    
    Args:
        connector: Neo4j 连接器
        
    Returns:
        ColdLayerManager 实例，失败返回 None
    """
    try:
        from config import load_config
        config = load_config()
        
        # 检查是否启用
        if not config.memory.enabled:
            logger.info("记忆系统未启用")
            return None
        
        return ColdLayerManager(connector, config)
        
    except Exception as e:
        logger.warning(f"冷层管理器初始化失败: {e}")
        return None

