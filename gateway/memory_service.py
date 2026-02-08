from __future__ import annotations

"""
记忆系统服务层

目标：
- 把 Gateway 中的"记忆"能力抽象成一个独立的 MemoryService
- 订阅事件总线上的 CHANNEL_MESSAGE 等事件，自动触发记忆保存/召回
- 通过事件总线发出记忆相关事件（MEMORY_SAVED / MEMORY_RECALLED 等）
- 保留原有 MemoryAdapter 的所有功能（保存消息、查询、聚类、摘要等）
"""

from typing import Any, Dict, Optional
from loguru import logger

from .events import EventEmitter
from .protocol import EventType
from core.services import get_memory_service


class MemoryService:
    """
    记忆服务（对 Gateway 暴露的统一入口）

    - 订阅事件总线上的消息事件，自动保存/召回记忆
    - 提供记忆查询/聚类/摘要等 API
    - 在 EventEmitter 上发出 MEMORY_* 事件，方便多 Agent 调度/监控
    - 内部复用现有的 MemoryAdapter，保留所有原有功能
    """

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        memory_adapter: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        
        # 复用现有的 MemoryAdapter（通过插件注册表获取或直接传入）
        self.memory_adapter = memory_adapter or get_memory_service()
        
        if not self.memory_adapter:
            logger.warning("MemoryService: Memory adapter not available, memory features will be disabled")
            self.enabled = False
        else:
            self.enabled = self.memory_adapter.is_enabled() if hasattr(self.memory_adapter, 'is_enabled') else False
            if self.enabled:
                logger.info("MemoryService: Memory adapter initialized and enabled")
            else:
                logger.info("MemoryService: Memory adapter available but disabled")
        
        # 订阅事件总线（如果提供了 EventEmitter）
        if self.event_emitter:
            self._subscribe_events()
    
    def _subscribe_events(self) -> None:
        """订阅事件总线上的相关事件"""
        if not self.event_emitter:
            return
        
        # 订阅通道消息事件，自动保存记忆
        self.event_emitter.on(EventType.CHANNEL_MESSAGE, self._on_channel_message)
        
        # 订阅配置变更事件（记忆系统配置变更时可能需要重新初始化）
        self.event_emitter.on(EventType.CONFIG_CHANGED, self._on_config_changed)
        self.event_emitter.on(EventType.CONFIG_RELOADED, self._on_config_reloaded)
        
        logger.debug("MemoryService: Subscribed to event bus")
    
    async def _on_config_changed(self, event_msg) -> None:
        """处理配置变更事件（用户级）"""
        try:
            payload = event_msg.payload
            user_id = payload.get("user_id")
            changes = payload.get("changes", {})
            
            # 如果记忆系统配置变更，记录日志
            if "memory" in changes:
                logger.info(f"MemoryService: Memory config changed for user {user_id}")
                # 注意：记忆系统配置变更通常不需要立即重新初始化
                # 因为 MemoryAdapter 在初始化时已经读取了配置
        
        except Exception as e:
            logger.error(f"MemoryService: Error handling config change: {e}")
    
    async def _on_config_reloaded(self, event_msg) -> None:
        """处理配置重载事件（系统级）"""
        try:
            logger.info("MemoryService: Default config reloaded")
            # 如果默认配置中的记忆系统配置变更，可能需要重新初始化
            # 但通常记忆系统配置在启动时确定，热重载记忆配置的风险较高
            # 这里只记录日志，不自动重新初始化
        
        except Exception as e:
            logger.error(f"MemoryService: Error handling config reload: {e}")
    
    async def _on_channel_message(self, event_msg) -> None:
        """
        处理通道消息事件，自动保存记忆
        
        事件 payload 格式：
        {
            "channel": "...",
            "sender": "...",
            "content": "...",
            "message_type": "...",
            "timestamp": "..."
        }
        """
        if not self.enabled or not self.memory_adapter:
            return
        
        try:
            payload = event_msg.payload
            content = payload.get("content", "")
            sender = payload.get("sender", "")
            channel = payload.get("channel", "")
            
            if not content:
                return
            
            # 构造 session_id（格式：channel_sender）
            session_id = f"{channel}_{sender}"
            user_id = sender  # 使用 sender 作为 user_id
            
            # 保存用户消息到记忆系统
            success = self.memory_adapter.add_message(
                session_id=session_id,
                role="user",
                content=content,
                user_id=user_id
            )
            
            if success:
                # 触发记忆维护（聚类/摘要/衰减）
                self.memory_adapter.on_message_saved(session_id, "user", user_id)
                
                # 发出记忆保存事件
                if self.event_emitter:
                    await self.event_emitter.emit(EventType.MEMORY_SAVED, {
                        "session_id": session_id,
                        "user_id": user_id,
                        "role": "user",
                        "content_length": len(content),
                        "channel": channel,
                    })
        
        except Exception as e:
            logger.error(f"MemoryService: Error handling channel message: {e}")
    
    # ===== 记忆查询 API =====
    
    async def get_context(
        self,
        query: str,
        session_id: str,
        user_id: Optional[str] = None
    ) -> str:
        """
        获取相关记忆上下文（自动召回）
        
        Args:
            query: 查询文本
            session_id: 会话ID
            user_id: 用户ID（可选）
            
        Returns:
            格式化的记忆上下文字符串
        """
        if not self.enabled or not self.memory_adapter:
            return ""
        
        try:
            context = self.memory_adapter.get_context(
                query=query,
                session_id=session_id,
                user_id=user_id or "default_user"
            )
            
            # 发出记忆召回事件
            if self.event_emitter and context:
                await self.event_emitter.emit(EventType.MEMORY_RECALLED, {
                    "session_id": session_id,
                    "user_id": user_id,
                    "query": query,
                    "context_length": len(context),
                })
            
            return context
        
        except Exception as e:
            logger.error(f"MemoryService: Error getting context: {e}")
            return ""
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None
    ) -> bool:
        """
        手动添加消息到记忆系统
        
        Args:
            session_id: 会话ID
            role: 角色（user/assistant）
            content: 消息内容
            user_id: 用户ID（可选）
            
        Returns:
            是否成功
        """
        if not self.enabled or not self.memory_adapter:
            return False
        
        try:
            success = self.memory_adapter.add_message(
                session_id=session_id,
                role=role,
                content=content,
                user_id=user_id or "default_user"
            )
            
            if success:
                # 触发记忆维护
                self.memory_adapter.on_message_saved(session_id, role, user_id or "default_user")
            
            return success
        
        except Exception as e:
            logger.error(f"MemoryService: Error adding message: {e}")
            return False
    
    # ===== 记忆维护 API =====
    
    async def cluster_entities(self, session_id: str) -> Dict[str, Any]:
        """
        对会话进行实体聚类（温层）
        
        Args:
            session_id: 会话ID
            
        Returns:
            聚类结果
        """
        if not self.enabled or not self.memory_adapter:
            return {"concepts_created": 0, "total_concepts": 0, "concepts": []}
        
        try:
            from memory import create_warm_layer_manager
            
            if not self.memory_adapter.hot_layer:
                return {"concepts_created": 0, "total_concepts": 0, "concepts": []}
            
            warm_layer = create_warm_layer_manager(self.memory_adapter.hot_layer.connector)
            concepts_created = warm_layer.cluster_entities(session_id)
            concepts = warm_layer.get_concepts(session_id)
            
            # 发出聚类事件
            if self.event_emitter:
                await self.event_emitter.emit(EventType.MEMORY_CLUSTERED, {
                    "session_id": session_id,
                    "concepts_created": concepts_created,
                    "total_concepts": len(concepts),
                })
            
            return {
                "concepts_created": concepts_created,
                "total_concepts": len(concepts),
                "concepts": concepts
            }
        
        except Exception as e:
            logger.error(f"MemoryService: Error clustering entities: {e}")
            return {"concepts_created": 0, "total_concepts": 0, "concepts": []}
    
    async def summarize_session(
        self,
        session_id: str,
        incremental: bool = False
    ) -> Dict[str, Any]:
        """
        对会话进行摘要（冷层）
        
        Args:
            session_id: 会话ID
            incremental: 是否增量摘要
            
        Returns:
            摘要结果
        """
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}
        
        try:
            from memory import create_cold_layer_manager
            
            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}
            
            cold_layer = create_cold_layer_manager(self.memory_adapter.hot_layer.connector)
            
            if not cold_layer.should_create_summary(session_id):
                return {"status": "skipped", "message": "Not enough messages or summary exists"}
            
            if incremental:
                summary_id = cold_layer.create_incremental_summary(session_id)
            else:
                summary_id = cold_layer.summarize_session(session_id)
            
            summary = cold_layer.get_summary_by_id(summary_id) if summary_id else None
            
            # 发出摘要事件
            if self.event_emitter and summary_id:
                await self.event_emitter.emit(EventType.MEMORY_SUMMARIZED, {
                    "session_id": session_id,
                    "summary_id": summary_id,
                    "incremental": incremental,
                })
            
            return {
                "session_id": session_id,
                "summary_id": summary_id,
                "summary": summary
            }
        
        except Exception as e:
            logger.error(f"MemoryService: Error summarizing session: {e}")
            return {"status": "error", "message": str(e)}
    
    async def apply_decay(self, session_id: str) -> Dict[str, Any]:
        """
        应用记忆衰减
        
        Args:
            session_id: 会话ID
            
        Returns:
            衰减结果
        """
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}
        
        try:
            from memory import create_forgetting_manager
            
            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}
            
            forgetting_manager = create_forgetting_manager(self.memory_adapter.hot_layer.connector)
            result = forgetting_manager.apply_time_decay(session_id)
            
            return result
        
        except Exception as e:
            logger.error(f"MemoryService: Error applying decay: {e}")
            return {"status": "error", "message": str(e)}
    
    async def cleanup_forgotten(self, session_id: str) -> Dict[str, Any]:
        """
        清理已遗忘的记忆节点
        
        Args:
            session_id: 会话ID
            
        Returns:
            清理结果
        """
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}
        
        try:
            from memory import create_forgetting_manager
            
            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}
            
            forgetting_manager = create_forgetting_manager(self.memory_adapter.hot_layer.connector)
            result = forgetting_manager.cleanup_forgotten(session_id)
            
            return result
        
        except Exception as e:
            logger.error(f"MemoryService: Error cleaning up forgotten: {e}")
            return {"status": "error", "message": str(e)}
    
    def is_enabled(self) -> bool:
        """检查记忆服务是否启用"""
        return self.enabled and self.memory_adapter is not None
