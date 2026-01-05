from pydantic import BaseModel
from time import monotonic
from typing import Dict, List, Optional
import logging
import uuid
from pydantic import Field
from .session_store import SessionStorage

logger = logging.getLogger(__name__)

def _model_to_dict(model: BaseModel) -> Dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()

class Message(BaseModel):
    role: str
    content: str

class Session(BaseModel):
    created_at: float = Field(default_factory = monotonic)
    last_activity: float = Field(default_factory = monotonic)
    agent_type: str = "default"
    messages: List[Message] = Field(default_factory = list)
    
class MessageManager:

    def __init__(self):
        
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
        
        try:
            from config import config
            self.max_history_rounds = config.api.max_history_rounds
            self.max_messages_per_session = self.max_history_rounds * 2
        except ImportError:
            self.max_history_rounds = 10
            self.max_messages_per_session = 20
            logger.warning("无法导入配置，使用默认最大轮数")
        
        # 集成记忆系统（通过适配器）
        self.memory_adapter = None
        try:
            from memory import get_memory_adapter
            self.memory_adapter = get_memory_adapter()
            if self.memory_adapter.is_enabled():
                logger.info("✅ 记忆系统已启用并集成到 MessageManager")
            else:
                logger.info("记忆系统未启用")
        except ImportError:
            logger.debug("记忆模块未安装")
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")

    def generate_session_id(self) -> str:

        return str(uuid.uuid4())
    
    def create_session(self, session_id: Optional[str] = None) -> str:

        if not session_id:
            session_id = self.generate_session_id()
        
        self.session[session_id] = Session()
        logger.info(f"创建新会话: {session_id}")

        self.session_store.save_all(self.session)
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:

        session = self.session.get(session_id)
        if not session:
            return None
        return {
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "agent_type": session.agent_type,
            "messages": [_model_to_dict(m) for m in session.messages]
        }
    
    def add_message(self, session_id: str, role: str, content: str) -> bool:

        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return False
        
        session = self.session[session_id]
        session.messages.append(Message(role=role, content=content))
        session.last_activity = monotonic()
        if len(session.messages) > self.max_messages_per_session:
            session.messages = session.messages[-self.max_messages_per_session:]
        
        logger.debug(f"会话 {session_id} 添加消息: {role} - {content[:50]}...")

        self.session_store.save_all(self.session)
        
        # 同步到记忆系统（如果启用，异步执行）
        if self.memory_adapter and self.memory_adapter.is_enabled():
            import asyncio
            try:
                # 使用 run_in_executor 将同步操作放入线程池，避免阻塞主线程
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None, 
                    self._sync_to_memory, 
                    session_id, role, content
                )
                logger.debug(f"已触发记忆系统异步同步: {session_id}")
            except Exception as e:
                logger.warning(f"记忆系统同步触发失败: {e}")

        return True
    
    def _sync_to_memory(self, session_id: str, role: str, content: str):
        """同步到记忆系统的辅助方法（在线程池中运行）"""
        try:
            self.memory_adapter.add_message(session_id, role, content)
            logger.debug(f"记忆系统同步完成: {session_id}")
        except Exception as e:
            logger.warning(f"记忆系统内部处理失败: {e}")
    
    def get_messages(self, session_id: str) -> List[Dict]:
        
        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return []
        session = self.session.get(session_id)
        return [_model_to_dict(m) for m in session.messages]
    
    def get_recent_messages(self, session_id: str, count: Optional[int] = None) -> List[Dict]:

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

        messages: List[Dict] = []
        messages.append({"role": "system", "content": system_prompt})
        if include_history:
            recent_messages = self.get_recent_messages(session_id)
            messages.extend(recent_messages)
        
        messages.append({"role": "user", "content": current_message})
        return messages
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:

        if session_id not in self.session:
            logger.warning(f"会话不存在: {session_id}")
            return None
        session = self.session.get(session_id)
        return {
            "session_id": session_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "message_count": len(session.messages),
            "conversation_rounds": len(session.messages) // 2,
            "agent_type": session.agent_type,
            "max_history_rounds": self.max_history_rounds,
            "last_message": (session.messages[-1].content[:100] + "...") if session.messages else "无对话历史"
        }
    
    def get_all_sessions_info(self) -> Dict[str, Dict]:

        sessions_info: Dict[str, Dict] = {}
        for sid in self.session.keys():
            sessions_info[sid] = self.get_session_info(sid)

        return sessions_info

    def delete_session(self, session_id: str) -> bool:

        if session_id in self.session:
            del self.session[session_id]
            logger.info(f"会话 {session_id} 已删除")
            self.session_store.save_all(self.session)
            return True
        return False
    
    def clear_all_sessions(self) -> int:
        count = len(self.session)
        self.session.clear()
        logger.info(f"已清空 {count} 个会话")

        self.session_store.save_all(self.session)
        return count
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:

        current_time = monotonic()
        expired_session_ids: List[str] = []

        for session_id, session in self.session.items():
            if current_time - session.last_activity > max_age_hours * 3600:
                expired_session_ids.append(session_id)
        for session_id in expired_session_ids:
            del self.session[session_id]
        
        if expired_session_ids:
            logger.info(f"已删除 {len(expired_session_ids)} 个过期会话")
            self.session_store.save_all(self.session)
        return len(expired_session_ids)

    def set_agent_type(self, session_id: str, agent_type: str) -> bool:
        
        if session_id in self.session:
            self.session[session_id].agent_type = agent_type
            return True

        return False

    def get_agent_type(self, session_id: str) -> Optional[str]:

        session = self.session.get(session_id)

        return session.agent_type if session else None

message_manager = MessageManager()