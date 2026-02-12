from __future__ import annotations
from typing import Any, Dict, List, Optional

from loguru import logger

from conversation_core import PrometheaConversation

from .events import EventEmitter
from .protocol import EventType


class ConversationService:
    """Gateway conversation orchestration service."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Optional[PrometheaConversation] = None,
        memory_service: Optional[Any] = None,
        message_manager: Optional[Any] = None,
        config_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core or PrometheaConversation()
        self.memory_service = memory_service
        self.message_manager = message_manager
        self.config_service = config_service

        logger.info("ConversationService: Initialized")
        if self.event_emitter:
            self._subscribe_events()

    def _subscribe_events(self) -> None:
        if not self.event_emitter:
            return
        self.event_emitter.on(EventType.CHANNEL_MESSAGE, self._on_channel_message)
        self.event_emitter.on(EventType.CONFIG_CHANGED, self._on_config_changed)
        self.event_emitter.on(EventType.CONFIG_RELOADED, self._on_config_reloaded)
        logger.debug("ConversationService: Subscribed to event bus")

    async def _on_config_changed(self, event_msg) -> None:
        try:
            payload = event_msg.payload
            user_id = payload.get("user_id")
            changes = payload.get("changes", {})
            if "api" in changes:
                logger.info(
                    "ConversationService: API config changed for user {}, will recreate client on next call",
                    user_id,
                )
        except Exception as e:
            logger.error("ConversationService: Error handling config change: {}", e)

    async def _on_config_reloaded(self, event_msg) -> None:
        try:
            logger.info("ConversationService: Default config reloaded")
        except Exception as e:
            logger.error("ConversationService: Error handling config reload: {}", e)

    async def _on_channel_message(self, event_msg) -> None:
        try:
            payload = event_msg.payload
            content = payload.get("content", "")
            sender = payload.get("sender", "")
            channel = payload.get("channel", "")
            if not content:
                return

            session_id = f"{channel}_{sender}"
            user_id = sender

            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_START,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "content": content,
                    },
                )

            await self._process_conversation(session_id, user_id, content, channel)
        except Exception as e:
            logger.error("ConversationService: Error handling channel message: {}", e)
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_ERROR,
                    {"error": str(e), "session_id": "unknown"},
                )

    async def _get_user_prompt_and_config(
        self,
        user_id: str,
        channel: str,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        base_system_prompt = ""
        user_config = None
        try:
            if self.config_service:
                merged = self.config_service.get_merged_config(user_id)
                base_system_prompt = (
                    merged.get("prompts", {}).get("Promethea_system_prompt", "")
                )
                user_config = self.config_service.get_user_config(user_id)
            else:
                from config import config

                base_system_prompt = getattr(
                    config.prompts, "Promethea_system_prompt", ""
                )
                from api_server.user_manager import user_manager

                user = user_manager.get_user_by_channel_account(channel, user_id)
                if user:
                    user_config = user_manager.get_user_config(user.get("user_id"))
        except Exception as e:
            logger.debug("ConversationService: Failed to get config: {}", e)
            from config import config

            base_system_prompt = getattr(config.prompts, "Promethea_system_prompt", "")

        return base_system_prompt, user_config

    async def _process_conversation(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str,
    ) -> None:
        try:
            user_config: Optional[Dict[str, Any]] = None
            system_prompt = ""
            messages: List[Dict[str, Any]] = []

            base_system_prompt, user_config = await self._get_user_prompt_and_config(
                user_id, channel
            )
            if user_config:
                custom_prompt = user_config.get("system_prompt")
                agent_name = user_config.get("agent_name")
                if custom_prompt:
                    base_system_prompt = custom_prompt
                if agent_name:
                    base_system_prompt = (
                        base_system_prompt.replace("Promethea", agent_name).replace(
                            "普罗米娅", agent_name
                        )
                    )

            memory_context = ""
            should_recall = await self._should_recall_memory(
                query=user_message,
                user_config=user_config,
                user_id=user_id,
            )
            if should_recall and self.memory_service and self.memory_service.is_enabled():
                memory_context = await self.memory_service.get_context(
                    query=user_message,
                    session_id=session_id,
                    user_id=user_id,
                )

            system_prompt = base_system_prompt
            if memory_context:
                system_prompt = (
                    f"{base_system_prompt}\n\n{memory_context}"
                    if base_system_prompt
                    else memory_context
                )

            if self.message_manager:
                if not self.message_manager.get_session(session_id):
                    self.message_manager.create_session(session_id)
                self.message_manager.add_message(
                    session_id,
                    "user",
                    user_message,
                    user_id,
                    sync_memory=False,
                )
                recent_messages = self.message_manager.get_recent_messages(session_id)
                messages = [{"role": "system", "content": system_prompt}] + recent_messages
            else:
                logger.warning(
                    "ConversationService: MessageManager not available, using stateless mode"
                )
                if system_prompt:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ]
                else:
                    messages = [{"role": "user", "content": user_message}]

            logger.info(
                "ConversationService: Processing conversation for session {}",
                session_id,
            )
            response_data = await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
            )
            reply_content = response_data.get("content", "")

            if self.message_manager and reply_content:
                self.message_manager.add_message(
                    session_id,
                    "assistant",
                    reply_content,
                    user_id,
                    sync_memory=False,
                )

            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_COMPLETE,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "response": reply_content,
                        "response_length": len(reply_content),
                        "status": response_data.get("status", "success"),
                    },
                )
                await self.event_emitter.emit(
                    EventType.INTERACTION_COMPLETED,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "user_input": user_message,
                        "assistant_output": reply_content,
                    },
                )
        except Exception as e:
            logger.error("ConversationService: Error processing conversation: {}", e)
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_ERROR,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "error": str(e),
                    },
                )

    async def _should_recall_memory(
        self,
        query: str,
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Ask the model whether long-term user context is needed for this query.
        """
        quick_decision = self._quick_recall_decision(
            query,
            user_config=user_config,
            user_id=user_id,
        )
        if quick_decision is not None:
            return quick_decision

        try:
            judge_prompt = (
                "You are a binary classifier. Decide whether answering the user query "
                "requires long-term user context (profile, preferences, constraints, "
                "goals, project history). Return strict JSON: {\"recall\": true|false}."
            )
            resp = await self.conversation_core.call_llm(
                [
                    {"role": "system", "content": judge_prompt},
                    {"role": "user", "content": query},
                ],
                user_config=user_config,
            )
            text = (resp or {}).get("content", "") or ""

            import json
            import re

            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return False
            data = json.loads(match.group(0))
            return bool(data.get("recall", False))
        except Exception:
            return False

    def _quick_recall_decision(
        self,
        query: str,
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Optional[bool]:
        """
        Cheap prefilter to reduce unnecessary LLM calls.
        Returns:
        - False: definitely do not recall
        - None: unsure, continue to LLM classifier
        """
        text = (query or "").strip()
        if not text:
            return False

        min_chars = 6
        max_chars = 4000
        try:
            if self.config_service:
                cfg = (
                    self.config_service.get_merged_config(user_id)
                    if user_id
                    else self.config_service.get_default_config().model_dump()
                )
                recall_cfg = (
                    cfg.get("memory", {})
                    .get("gating", {})
                    .get("recall_filter", {})
                )
                min_chars = int(recall_cfg.get("min_query_chars", min_chars))
                max_chars = int(recall_cfg.get("max_query_chars", max_chars))
        except Exception:
            pass

        if len(text) < min_chars:
            return False
        if len(text) > max_chars:
            return False

        return None

    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict:
        return await self.conversation_core.run_chat_loop(
            messages,
            user_config=user_config,
            session_id=session_id,
        )

    async def call_llm(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        return await self.conversation_core.call_llm(messages, user_config=user_config)

    async def call_llm_stream(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
    ):
        async for chunk in self.conversation_core.call_llm_stream(
            messages,
            user_config=user_config,
        ):
            yield chunk
