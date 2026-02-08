from __future__ import annotations

"""
对话系统服务层

目标：
- 把 Gateway 中的"对话"能力抽象成一个独立的 ConversationService
- 订阅事件总线上的 CHANNEL_MESSAGE 事件，自动处理对话流程
- 通过事件总线发出对话相关事件（CONVERSATION_START / CONVERSATION_COMPLETE 等）
- 保留原有 PrometheaConversation 的所有功能（LLM 调用、工具调用循环等）
"""

from typing import Any, Dict, Optional, List
from loguru import logger

from .events import EventEmitter
from .protocol import EventType
from conversation_core import PrometheaConversation


class ConversationService:
    """
    对话服务（对 Gateway 暴露的统一入口）

    - 订阅事件总线上的消息事件，自动处理对话流程
    - 提供 LLM 调用、工具调用循环等 API
    - 在 EventEmitter 上发出 CONVERSATION_* 事件，方便多 Agent 调度/监控
    - 内部复用现有的 PrometheaConversation，保留所有原有功能
    """

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Optional[PrometheaConversation] = None,
        memory_service: Optional[Any] = None,
        message_manager: Optional[Any] = None,
        config_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        
        # 复用现有的 PrometheaConversation（或创建新实例）
        self.conversation_core = conversation_core or PrometheaConversation()
        
        # 依赖其他服务（可选）
        self.memory_service = memory_service
        self.message_manager = message_manager
        self.config_service = config_service
        
        logger.info("ConversationService: Initialized")
        
        # 订阅事件总线（如果提供了 EventEmitter）
        if self.event_emitter:
            self._subscribe_events()
    
    def _subscribe_events(self) -> None:
        """订阅事件总线上的相关事件"""
        if not self.event_emitter:
            return
        
        # 订阅通道消息事件，自动处理对话
        self.event_emitter.on(EventType.CHANNEL_MESSAGE, self._on_channel_message)
        
        # 订阅配置变更事件，实现热重载
        self.event_emitter.on(EventType.CONFIG_CHANGED, self._on_config_changed)
        self.event_emitter.on(EventType.CONFIG_RELOADED, self._on_config_reloaded)
        
        logger.debug("ConversationService: Subscribed to event bus")
    
    async def _on_config_changed(self, event_msg) -> None:
        """
        处理配置变更事件（用户级）
        
        当用户配置变更时，重新初始化 LLM 客户端（如果需要）
        """
        try:
            payload = event_msg.payload
            user_id = payload.get("user_id")
            changes = payload.get("changes", {})
            
            # 如果 API 配置变更，需要重新创建客户端
            if "api" in changes:
                logger.info(f"ConversationService: API config changed for user {user_id}, will recreate client on next call")
                # 注意：这里不立即重新创建，而是在下次调用时根据 user_config 动态创建
                # 因为 conversation_core.call_llm 已经支持 user_config 参数
            
            logger.debug(f"ConversationService: Config changed for user {user_id}")
        
        except Exception as e:
            logger.error(f"ConversationService: Error handling config change: {e}")
    
    async def _on_config_reloaded(self, event_msg) -> None:
        """
        处理配置重载事件（系统级）
        
        当默认配置重载时，记录日志（如果需要可以重新初始化）
        """
        try:
            logger.info("ConversationService: Default config reloaded")
            # 注意：默认配置变更通常不需要立即重新初始化 conversation_core
            # 因为 conversation_core 在初始化时已经读取了配置
            # 如果需要支持默认配置热重载，可以在这里重新创建 conversation_core
        
        except Exception as e:
            logger.error(f"ConversationService: Error handling config reload: {e}")
    
    async def _on_channel_message(self, event_msg) -> None:
        """
        处理通道消息事件，自动触发对话流程
        
        事件 payload 格式：
        {
            "channel": "...",
            "sender": "...",
            "content": "...",
            "message_type": "...",
            "timestamp": "..."
        }
        """
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
            
            # 发出对话开始事件
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONVERSATION_START, {
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                    "content": content,
                })
            
            # 处理对话（异步执行，不阻塞事件处理）
            # 注意：这里我们不在事件处理函数中直接 await，而是创建任务
            # 但为了保持简单，我们先同步执行，后续可以优化为异步任务
            await self._process_conversation(session_id, user_id, content, channel)
        
        except Exception as e:
            logger.error(f"ConversationService: Error handling channel message: {e}")
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONVERSATION_ERROR, {
                    "error": str(e),
                    "session_id": payload.get("session_id", "unknown") if 'payload' in locals() else "unknown",
                })
    
    async def _process_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str
    ) -> None:
        """
        处理对话流程（内部方法）
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
            user_message: 用户消息
            channel: 通道名称
        """
        try:
            # 1. 构建消息上下文
            messages = []
            
            # 1.1 尝试从 message_manager 获取历史记录
            if self.message_manager:
                # 确保会话存在
                if not self.message_manager.get_session(session_id):
                    self.message_manager.create_session(session_id)
                
                # 1.2 自动召回长期记忆（如果 memory_service 可用）
                memory_context = ""
                if self.memory_service and self.memory_service.is_enabled():
                    memory_context = await self.memory_service.get_context(
                        query=user_message,
                        session_id=session_id,
                        user_id=user_id
                    )
                
                # 1.3 构建系统提示词（含记忆）
                # 优先从 ConfigService 获取配置（如果可用），否则降级到直接 import
                base_system_prompt = ""
                user_config = None
                
                try:
                    if self.config_service:
                        # 使用 ConfigService 获取配置
                        merged_config = self.config_service.get_merged_config(user_id)
                        base_system_prompt = merged_config.get("prompts", {}).get("Promethea_system_prompt", "")
                        user_config = self.config_service.get_user_config(user_id)
                    else:
                        # 降级：直接获取
                        from config import config
                        base_system_prompt = getattr(config.prompts, "Promethea_system_prompt", "")
                        from api_server.user_manager import user_manager
                        user = user_manager.get_user_by_channel_account(channel, user_id)
                        if user:
                            user_config = user_manager.get_user_config(user.get('user_id'))
                except Exception as e:
                    logger.debug(f"ConversationService: Failed to get config: {e}")
                    # 最终降级
                    from config import config
                    base_system_prompt = getattr(config.prompts, "Promethea_system_prompt", "")
                
                # 如果绑定了用户，加载用户个性化配置
                if user_config:
                    custom_prompt = user_config.get('system_prompt')
                    agent_name = user_config.get('agent_name')
                    if custom_prompt:
                        base_system_prompt = custom_prompt
                    if agent_name:
                        base_system_prompt = base_system_prompt.replace("Promethea", agent_name).replace("普罗米娅", agent_name)
                
                system_prompt = base_system_prompt
                if memory_context:
                    system_prompt += f"\n\n{memory_context}"
                
                # 添加用户消息到历史
                self.message_manager.add_message(session_id, "user", user_message, user_id)
                
                # 1.4 构建完整对话上下文（System + History + User）
                recent_messages = self.message_manager.get_recent_messages(session_id)
                messages = [{"role": "system", "content": system_prompt}] + recent_messages
            else:
                # 降级处理：无记忆
                logger.warning("ConversationService: MessageManager not available, using stateless mode")
                messages = [{"role": "user", "content": user_message}]
                # 在无记忆模式下也尝试获取用户配置（用于 API 配置）
                user_config = None
                try:
                    if self.config_service:
                        user_config = self.config_service.get_user_config(user_id)
                    else:
                        from api_server.user_manager import user_manager
                        user = user_manager.get_user_by_channel_account(channel, user_id)
                        if user:
                            user_config = user_manager.get_user_config(user.get('user_id'))
                except Exception as e:
                    logger.debug(f"ConversationService: Failed to get user config: {e}")
            
            # 2. 调用对话核心逻辑
            logger.info(f"ConversationService: Processing conversation for session {session_id}")
            
            # 运行对话循环（包含工具调用）
            response_data = await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id
            )
            
            reply_content = response_data.get("content", "")
            
            # 3. 保存回复到历史（如果 message_manager 可用）
            if self.message_manager and reply_content:
                self.message_manager.add_message(session_id, "assistant", reply_content, user_id)
            
            # 4. 发出对话完成事件（包含回复内容，供 gateway_integration 发送给渠道）
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONVERSATION_COMPLETE, {
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                    "response": reply_content,  # 包含完整回复内容
                    "response_length": len(reply_content),
                    "status": response_data.get("status", "success"),
                })
            
            # 5. 保存记忆（如果 memory_service 可用）
            if self.memory_service and self.memory_service.is_enabled() and reply_content:
                self.memory_service.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=reply_content,
                    user_id=user_id
                )
        
        except Exception as e:
            logger.error(f"ConversationService: Error processing conversation: {e}")
            if self.event_emitter:
                await self.event_emitter.emit(EventType.CONVERSATION_ERROR, {
                    "session_id": session_id,
                    "user_id": user_id,
                    "error": str(e),
                })
    
    # ===== 对话 API（供 Gateway handler 直接调用） =====
    
    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict:
        """
        运行带工具调用的对话循环
        
        Args:
            messages: 消息列表
            user_config: 用户配置（可选）
            session_id: 会话ID（可选）
            
        Returns:
            对话结果
        """
        return await self.conversation_core.run_chat_loop(
            messages,
            user_config=user_config,
            session_id=session_id
        )
    
    async def call_llm(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None
    ) -> Dict:
        """
        调用 LLM API
        
        Args:
            messages: 消息列表
            user_config: 用户配置（可选）
            
        Returns:
            LLM 响应
        """
        return await self.conversation_core.call_llm(messages, user_config=user_config)
    
    async def call_llm_stream(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None
    ):
        """
        流式调用 LLM API
        
        Args:
            messages: 消息列表
            user_config: 用户配置（可选）
            
        Yields:
            LLM 响应块
        """
        async for chunk in self.conversation_core.call_llm_stream(messages, user_config=user_config):
            yield chunk
