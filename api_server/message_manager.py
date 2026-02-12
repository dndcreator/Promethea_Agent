from pydantic import BaseModel, Field
import time
from typing import Dict, List, Optional
import logging
import uuid

try:
    # pydantic v2
    from pydantic import field_validator
except Exception:  # pragma: no cover
    field_validator = None

from .session_store import SessionStorage

logger = logging.getLogger(__name__)


def _model_to_dict(model: BaseModel) -> Dict:
    """兼容 pydantic v1/v2 的模型转字典辅助函数。"""
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class Message(BaseModel):
    role: str
    content: str


class Session(BaseModel):
    """
    会话模型：
    - 使用 Unix epoch 秒，前端可以直接 new Date(ts * 1000) 展示
    - 兼容旧版本曾写入的 monotonic 值：加载时自动重置为当前时间
    """

    created_at: float = Field(default_factory=time.time)
    last_activity: float = Field(default_factory=time.time)
    agent_type: str = "default"
    messages: List[Message] = Field(default_factory=list)

    # 待确认的工具调用状态
    pending_confirmation: Optional[Dict] = None

    if field_validator:

        @field_validator("created_at", "last_activity", mode="before")
        @classmethod
        def _coerce_epoch_seconds(cls, v):
            """将异常/旧格式时间值纠正为当前时间或合法的 epoch 秒。"""
            try:
                if v is None:
                    return time.time()
                v = float(v)
            except Exception:
                return time.time()

            # 2001-09-09 01:46:40Z 约等于 1e9，小于这个基本可视为旧的 monotonic 值
            if v < 1_000_000_000:
                return time.time()
            return v
    

class MessageManager:
    """管理会话、消息历史，并与记忆系统进行集成的核心组件。"""

    def __init__(self):
        # 会话持久化存储
        self.session_store = SessionStorage()
        self.session: Dict[str, Session] = {}
        
        # 加载已保存的会话
        try:
            saved_sessions = self.session_store.load_all()
            self.session.update(saved_sessions)
            if saved_sessions:
                logger.info(f"✅ 从磁盘加载了 {len(saved_sessions)} 个会话")
        except Exception as e:
            logger.warning(f"加载会话失败: {e}")
        
        # 最大历史轮数配置
        try:
            from config import config

            self.max_history_rounds = config.api.max_history_rounds
            self.max_messages_per_session = self.max_history_rounds * 2
        except ImportError:
            self.max_history_rounds = 10
            self.max_messages_per_session = 20
            logger.warning("无法导入配置，使用默认最大轮数")
        
        # 集成记忆系统（通过插件注册表获取，实现解耦）
        self.memory_adapter = None
        try:
            from core.services import get_memory_service

            self.memory_adapter = get_memory_service()
            if self.memory_adapter and self.memory_adapter.is_enabled():
                logger.info("✅ 记忆系统已启用并集成到 MessageManager")
            else:
                logger.info("记忆系统未启用")
        except ImportError:
            logger.debug("核心服务模块未安装，跳过记忆系统集成")
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")

    def generate_session_id(self) -> str:
        """生成新的会话 ID。"""
        return str(uuid.uuid4())
    
    def create_session(self, session_id: Optional[str] = None) -> str:
        """创建一个新的会话。"""
        if not session_id:
            session_id = self.generate_session_id()
        
        self.session[session_id] = Session()
        logger.info(f"创建新会话: {session_id}")

        self.session_store.save_all(self.session)
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话的完整信息（不含 pending_confirmation）。"""
        session = self.session.get(session_id)
        if not session:
            return None
        return {
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "agent_type": session.agent_type,
            "messages": [_model_to_dict(m) for m in session.messages],
        }
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "default_user",
        sync_memory: bool = True,
    ) -> bool:
        """向会话追加一条消息，并异步同步到记忆系统。"""
        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return False
        
        session = self.session[session_id]
        session.messages.append(Message(role=role, content=content))
        session.last_activity = time.time()

        if len(session.messages) > self.max_messages_per_session:
            session.messages = session.messages[-self.max_messages_per_session :]
        
        logger.debug(f"会话 {session_id} 新增消息: {role} - {content[:50]}...")

        self.session_store.save_all(self.session)
        
        # 同步到记忆系统（如果启用），放到线程池中执行，避免阻塞主事件循环
        if sync_memory and self.memory_adapter and self.memory_adapter.is_enabled():
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None, 
                    self._sync_to_memory, 
                    session_id,
                    role,
                    content,
                    user_id,
                )
                logger.debug(f"已触发记忆系统异步同步: {session_id}")
            except Exception as e:
                logger.warning(f"记忆系统同步触发失败: {e}")

        return True
    
    def _sync_to_memory(self, session_id: str, role: str, content: str, user_id: str = "default_user"):
        """在后台线程中执行的同步逻辑，写入记忆系统并触发维护任务。"""
        try:
            if not self.memory_adapter or not self.memory_adapter.is_enabled():
                return

            # 1. 写入热层记忆
            try:
                self.memory_adapter.add_message(session_id, role, content, user_id)
            except Exception as e:
                logger.warning(f"记忆系统 add_message 失败: {e}")

            # 2. 触发维护逻辑（聚类/摘要/遗忘），不会阻塞主流程
            try:
                if hasattr(self.memory_adapter, "on_message_saved"):
                    self.memory_adapter.on_message_saved(session_id, role, user_id)
            except Exception as e:
                logger.warning(f"记忆系统维护任务触发失败: {e}")

            logger.debug(f"记忆系统同步完成: {session_id}")
        except Exception as e:
            logger.warning(f"记忆系统内部处理失败: {e}")
    
    def get_messages(self, session_id: str) -> List[Dict]:
        """获取某个会话的全部消息。"""
        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return []
        session = self.session.get(session_id)
        return [_model_to_dict(m) for m in session.messages]
    
    def get_recent_messages(self, session_id: str, count: Optional[int] = None) -> List[Dict]:
        """获取会话最近 N 条消息。"""
        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return []
        if count is None:
            count = self.max_messages_per_session
        messages = self.get_messages(session_id)
        return messages[-count:] if messages else []
    
    def build_conversation(
        self, 
        session_id: str, 
        system_prompt: str,
        current_message: str,
        include_history: bool = True,
    ) -> List[Dict]:
        """构造发送给 LLM 的消息列表。"""
        messages: List[Dict] = []
        messages.append({"role": "system", "content": system_prompt})

        if include_history:
            recent_messages = self.get_recent_messages(session_id)
            messages.extend(recent_messages)
        
        messages.append({"role": "user", "content": current_message})
        return messages
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """获取单个会话的概要信息（用于列表展示）。"""
        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return None
        session = self.session.get(session_id)
        last_msg_preview = (
            session.messages[-1].content[:100] + "..." if session.messages else ""
        )
        return {
            "session_id": session_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "message_count": len(session.messages),
            "conversation_rounds": len(session.messages) // 2,
            "agent_type": session.agent_type,
            "max_history_rounds": self.max_history_rounds,
            "last_message": last_msg_preview,
        }
    
    def get_all_sessions_info(self) -> Dict[str, Dict]:
        """获取所有会话的概要信息。"""
        sessions_info: Dict[str, Dict] = {}
        for sid in self.session.keys():
            sessions_info[sid] = self.get_session_info(sid)
        return sessions_info

    def delete_session(self, session_id: str) -> bool:
        """删除单个会话。"""
        if session_id in self.session:
            del self.session[session_id]
            logger.info(f"会话 {session_id} 已删除")
            self.session_store.save_all(self.session)
            return True
        return False
    
    def clear_all_sessions(self) -> int:
        """清空所有会话。"""
        count = len(self.session)
        self.session.clear()
        logger.info(f"已清空 {count} 个会话")
        self.session_store.save_all(self.session)
        return count
    
    def cleanup_old_sessions(self, max_age_hours: int = 0) -> int:
        """
        清理过期会话。

        默认不自动清理（max_age_hours=0），以符合“长期保存会话”的产品预期。
        如需清理，可在管理接口中显式调用并传入小时数。
        """
        if max_age_hours <= 0:
            return 0

        current_time = time.time()
        expired_session_ids: List[str] = []

        for session_id, session in list(self.session.items()):
            if current_time - session.last_activity > max_age_hours * 3600:
                expired_session_ids.append(session_id)

        for session_id in expired_session_ids:
            del self.session[session_id]
        
        if expired_session_ids:
            logger.info(f"已删除 {len(expired_session_ids)} 个过期会话")
            self.session_store.save_all(self.session)
        return len(expired_session_ids)

    def set_pending_confirmation(self, session_id: str, confirmation_data: Dict) -> bool:
        """为会话设置待确认的工具调用状态。"""
        if session_id in self.session:
            self.session[session_id].pending_confirmation = confirmation_data
            self.session_store.save_all(self.session)
            return True
        return False

    def get_pending_confirmation(self, session_id: str) -> Optional[Dict]:
        """获取会话当前的待确认工具调用状态。"""
        if session_id in self.session:
            return self.session[session_id].pending_confirmation
        return None

    def clear_pending_confirmation(self, session_id: str):
        """清除会话中的待确认工具调用状态。"""
        if session_id in self.session:
            self.session[session_id].pending_confirmation = None
            self.session_store.save_all(self.session)

    def set_agent_type(self, session_id: str, agent_type: str) -> bool:
        """设置会话所绑定的 agent 类型。"""
        if session_id in self.session:
            self.session[session_id].agent_type = agent_type
            return True
        return False

    def get_agent_type(self, session_id: str) -> Optional[str]:
        """获取会话所绑定的 agent 类型。"""
        session = self.session.get(session_id)
        return session.agent_type if session else None


# 全局单例实例，供路由等模块直接使用
message_manager = MessageManager()

