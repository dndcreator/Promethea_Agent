"""
记忆系统适配器
解决对话系统和记忆系统接口不一致的问题
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """
    记忆系统适配器
    
    将 MessageManager 的简单接口适配到 HotLayerManager 的复杂接口
    """
    
    def __init__(self):
        """初始化适配器"""
        self.enabled = False
        self.hot_layer = None
        self.recall_engine = None
        self._session_cache = {}  # 缓存每个 session 的消息历史
        self._init_memory_system()
    
    def _init_memory_system(self):
        """初始化记忆系统（失败不抛异常）"""
        try:
            from config import load_config
            config = load_config()
            
            # 检查是否启用
            if not config.memory.enabled:
                logger.info("记忆系统未启用（config.memory.enabled = false）")
                return
            
            # 使用工厂函数创建
            from memory import create_hot_layer_manager
            self.hot_layer = create_hot_layer_manager("_adapter_init")
            
            if self.hot_layer:
                # 初始化召回引擎
                from .auto_recall import AutoRecallEngine
                self.recall_engine = AutoRecallEngine(
                    connector=self.hot_layer.connector,
                    extractor=self.hot_layer.extractor
                )
                self.enabled = True
                logger.info("✅ 记忆系统适配器初始化成功（含召回引擎）")
            else:
                logger.info("记忆系统不可用（Neo4j 未连接或配置错误）")
                
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")
            self.enabled = False
    
    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """
        添加消息到记忆系统
        
        接口与 MessageManager.add_message 一致
        
        Args:
            session_id: 会话ID
            role: 角色 (user/assistant)
            content: 消息内容
            
        Returns:
            是否成功
        """
        if not self.enabled or not self.hot_layer:
            return False
        
        try:
            # 更新 session_id（HotLayerManager 是有状态的）
            self.hot_layer.session_id = session_id
            
            # 获取上下文（从缓存）
            context = self._get_context(session_id)
            
            # 调用记忆系统
            stats = self.hot_layer.process_message(role, content, context)
            
            # 更新缓存
            self._update_cache(session_id, role, content)
            
            logger.debug(f"记忆已保存: {stats}")
            return True
            
        except Exception as e:
            logger.error(f"记忆系统处理失败: {e}")
            return False
    
    def _get_context(self, session_id: str) -> list:
        """获取会话上下文（最近5条消息）"""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        return self._session_cache[session_id][-5:]  # 只取最近5条
    
    def _update_cache(self, session_id: str, role: str, content: str):
        """更新上下文缓存"""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        
        self._session_cache[session_id].append({
            "role": role,
            "content": content
        })
        
        # 限制缓存大小（最多保留10条）
        if len(self._session_cache[session_id]) > 10:
            self._session_cache[session_id] = self._session_cache[session_id][-10:]
    
    def get_context(self, query: str, session_id: str) -> str:
        """
        获取相关记忆上下文（自动召回）
        
        Args:
            query: 用户当前消息
            session_id: 会话ID
            
        Returns:
            格式化的上下文字符串
        """
        if not self.enabled or not self.recall_engine:
            return ""
        
        try:
            return self.recall_engine.recall(query, session_id)
        except Exception as e:
            logger.error(f"获取记忆上下文失败: {e}")
            return ""
    
    def is_enabled(self) -> bool:
        """检查记忆系统是否可用"""
        return self.enabled and self.hot_layer is not None


# 全局单例
_memory_adapter_instance: Optional[MemoryAdapter] = None


def get_memory_adapter() -> MemoryAdapter:
    """获取全局记忆适配器实例"""
    global _memory_adapter_instance
    if _memory_adapter_instance is None:
        _memory_adapter_instance = MemoryAdapter()
    return _memory_adapter_instance

