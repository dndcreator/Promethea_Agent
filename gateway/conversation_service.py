from __future__ import annotations
import asyncio
import time
import uuid
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
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._session_workers: Dict[str, asyncio.Task] = {}
        self._queue_lock = asyncio.Lock()
        self._processing_defaults = {
            "max_queue_size": 32,
            "max_retries": 2,
            "retry_base_delay_s": 0.8,
            "retry_max_delay_s": 8.0,
            "worker_idle_ttl_s": 300.0,
        }

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
            policy = self._resolve_processing_policy(user_id)
            enqueued = await self._enqueue_message(
                session_id=session_id,
                item={
                    "session_id": session_id,
                    "user_id": user_id,
                    "content": content,
                    "channel": channel,
                    "turn_id": str(uuid.uuid4()),
                    "attempt": 0,
                    "enqueued_at": time.time(),
                },
                policy=policy,
            )
            if not enqueued:
                logger.warning(
                    "ConversationService: Session queue full, drop message, session={}",
                    session_id,
                )
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.CONVERSATION_ERROR,
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "error": "session queue is full",
                        },
                    )
                return

            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_START,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "content": content,
                        "queued": True,
                    },
                )
        except Exception as e:
            logger.error("ConversationService: Error handling channel message: {}", e)
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.CONVERSATION_ERROR,
                    {"error": str(e), "session_id": "unknown"},
                )

    def _resolve_processing_policy(self, user_id: str) -> Dict[str, float]:
        policy = dict(self._processing_defaults)
        try:
            if self.config_service:
                cfg = self.config_service.get_merged_config(user_id)
                proc = cfg.get("conversation", {}).get("processing", {})
                policy["max_queue_size"] = int(
                    proc.get("max_queue_size", policy["max_queue_size"])
                )
                policy["max_retries"] = int(
                    proc.get("max_retries", policy["max_retries"])
                )
                policy["retry_base_delay_s"] = float(
                    proc.get("retry_base_delay_s", policy["retry_base_delay_s"])
                )
                policy["retry_max_delay_s"] = float(
                    proc.get("retry_max_delay_s", policy["retry_max_delay_s"])
                )
                policy["worker_idle_ttl_s"] = float(
                    proc.get("worker_idle_ttl_s", policy["worker_idle_ttl_s"])
                )
        except Exception as e:
            logger.debug("ConversationService: Using default processing policy: {}", e)

        policy["max_queue_size"] = max(1, int(policy["max_queue_size"]))
        policy["max_retries"] = max(0, int(policy["max_retries"]))
        policy["retry_base_delay_s"] = max(0.1, float(policy["retry_base_delay_s"]))
        policy["retry_max_delay_s"] = max(
            policy["retry_base_delay_s"], float(policy["retry_max_delay_s"])
        )
        policy["worker_idle_ttl_s"] = max(5.0, float(policy["worker_idle_ttl_s"]))
        return policy

    async def _enqueue_message(
        self,
        session_id: str,
        item: Dict[str, Any],
        policy: Dict[str, float],
    ) -> bool:
        async with self._queue_lock:
            queue = self._session_queues.get(session_id)
            if queue is None:
                queue = asyncio.Queue(maxsize=int(policy["max_queue_size"]))
                self._session_queues[session_id] = queue
            if queue.full():
                return False
            queue.put_nowait(item)
            if session_id not in self._session_workers:
                worker = asyncio.create_task(
                    self._session_worker(session_id, policy)
                )
                self._session_workers[session_id] = worker
            return True

    async def _session_worker(self, session_id: str, policy: Dict[str, float]) -> None:
        idle_ttl = float(policy["worker_idle_ttl_s"])
        queue = self._session_queues[session_id]
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=idle_ttl)
                except asyncio.TimeoutError:
                    if queue.empty():
                        break
                    continue
                try:
                    await self._process_with_retry(item, policy)
                finally:
                    queue.task_done()
        finally:
            async with self._queue_lock:
                self._session_workers.pop(session_id, None)
                q = self._session_queues.get(session_id)
                if q is not None and q.empty():
                    self._session_queues.pop(session_id, None)

    async def _process_with_retry(
        self,
        item: Dict[str, Any],
        policy: Dict[str, float],
    ) -> None:
        max_retries = int(policy["max_retries"])
        base_delay = float(policy["retry_base_delay_s"])
        max_delay = float(policy["retry_max_delay_s"])
        attempt = int(item.get("attempt", 0))
        session_id = item["session_id"]
        user_id = item["user_id"]

        while True:
            try:
                await self._process_conversation_once(
                    session_id=session_id,
                    user_id=user_id,
                    user_message=item["content"],
                    channel=item["channel"],
                    turn_id=item.get("turn_id"),
                )
                return
            except Exception as e:
                if attempt >= max_retries:
                    logger.error(
                        "ConversationService: Conversation failed after retries, session={}, error={}",
                        session_id,
                        e,
                    )
                    if self.event_emitter:
                        await self.event_emitter.emit(
                            EventType.CONVERSATION_ERROR,
                            {
                                "session_id": session_id,
                                "user_id": user_id,
                                "error": str(e),
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "will_retry": False,
                            },
                        )
                    if self.message_manager and item.get("turn_id") and hasattr(
                        self.message_manager, "abort_turn"
                    ):
                        try:
                            self.message_manager.abort_turn(
                                session_id, item["turn_id"], user_id=user_id
                            )
                        except Exception:
                            pass
                    return

                delay = min(max_delay, base_delay * (2 ** attempt))
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.CONVERSATION_ERROR,
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "error": str(e),
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "will_retry": True,
                            "retry_delay_s": delay,
                        },
                    )
                logger.warning(
                    "ConversationService: Retry conversation, session={}, attempt={}/{}, delay={}s",
                    session_id,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

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
                from gateway.http.user_manager import user_manager

                user = user_manager.get_user_by_channel_account(channel, user_id)
                if user:
                    user_config = user_manager.get_user_config(user.get("user_id"))
        except Exception as e:
            logger.debug("ConversationService: Failed to get config: {}", e)
            from config import config

            base_system_prompt = getattr(config.prompts, "Promethea_system_prompt", "")

        return base_system_prompt, user_config

    async def _process_conversation_once(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str,
        turn_id: Optional[str] = None,
    ) -> None:
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
                        "your assistant", agent_name
                    )
                )

        system_prompt = await self.build_system_prompt_with_memory(
            query=user_message,
            session_id=session_id,
            user_id=user_id,
            user_config=user_config,
            base_system_prompt=base_system_prompt,
        )

        if self.message_manager:
            if not self.message_manager.get_session(session_id, user_id=user_id):
                self.message_manager.create_session(session_id, user_id=user_id)
            if turn_id and hasattr(self.message_manager, "begin_turn"):
                ok = self.message_manager.begin_turn(
                    session_id=session_id,
                    turn_id=turn_id,
                    user_role="user",
                    user_content=user_message,
                    user_id=user_id,
                )
                if not ok:
                    raise RuntimeError(
                        f"failed to begin conversation turn: {session_id}:{turn_id}"
                    )
            recent_messages = self.message_manager.get_recent_messages(
                session_id, user_id=user_id
            )
            messages = (
                [{"role": "system", "content": system_prompt}]
                + recent_messages
                + [{"role": "user", "content": user_message}]
            )
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
        try:
            response_data = await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
                user_id=user_id,
            )
        except TypeError:
            # Backward compatibility for conversation_core mocks without user_id arg.
            response_data = await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
            )
        reply_content = response_data.get("content", "")

        if self.message_manager:
            if turn_id and hasattr(self.message_manager, "commit_turn"):
                committed = self.message_manager.commit_turn(
                    session_id=session_id,
                    turn_id=turn_id,
                    assistant_content=reply_content or "",
                    user_id=user_id,
                )
                if not committed:
                    raise RuntimeError(
                        f"failed to commit conversation turn: {session_id}:{turn_id}"
                    )
            elif reply_content:
                self.message_manager.add_message(
                    session_id,
                    "user",
                    user_message,
                    user_id,
                    sync_memory=False,
                )
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
                user_id=user_id,
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

        if self._is_explicit_memory_query(text):
            # Explicit memory/profile lookup should bypass short-query rejection.
            return True
        if len(text) < min_chars:
            return False
        if len(text) > max_chars:
            return False

        return None

    @staticmethod
    def _is_explicit_memory_query(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        cn_markers = (
            "我叫什么",
            "我叫啥",
            "我的名字",
            "你记得我",
            "你还记得",
            "我是谁",
            "我的偏好",
            "我的设定",
        )
        en_markers = (
            "what is my name",
            "who am i",
            "do you remember me",
            "remember my name",
            "my preference",
            "my profile",
        )
        return any(m in lowered for m in cn_markers) or any(
            m in lowered for m in en_markers
        )

    async def build_system_prompt_with_memory(
        self,
        query: str,
        session_id: str,
        user_id: Optional[str],
        user_config: Optional[Dict[str, Any]] = None,
        base_system_prompt: str = "",
    ) -> str:
        """
        Build final system prompt with optional memory recall context.
        Keeps recall-gating logic shared between stream and non-stream paths.
        """
        should_recall = await self._should_recall_memory(
            query=query,
            user_config=user_config,
            user_id=user_id,
        )
        memory_context = ""
        if (
            should_recall
            and self.memory_service
            and self.memory_service.is_enabled()
            and session_id
            and user_id
        ):
            memory_context = await self.memory_service.get_context(
                query=query,
                session_id=session_id,
                user_id=user_id,
            )
        if memory_context:
            return (
                f"{base_system_prompt}\n\n{memory_context}"
                if base_system_prompt
                else memory_context
            )
        return base_system_prompt

    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tool_executor=None,
    ) -> Dict:
        try:
            return await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
                user_id=user_id,
                tool_executor=tool_executor,
            )
        except TypeError:
            return await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
            )

    async def call_llm(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict:
        try:
            return await self.conversation_core.call_llm(
                messages,
                user_config=user_config,
                user_id=user_id,
            )
        except TypeError:
            return await self.conversation_core.call_llm(
                messages,
                user_config=user_config,
            )

    async def call_llm_stream(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ):
        async for chunk in self.conversation_core.call_llm_stream(
            messages,
            user_config=user_config,
            user_id=user_id,
        ):
            yield chunk

    def get_processing_stats(self) -> Dict[str, Any]:
        queue_sizes = {
            sid: q.qsize() for sid, q in self._session_queues.items()
        }
        return {
            "sessions_with_queue": len(queue_sizes),
            "active_workers": len(self._session_workers),
            "queued_messages": sum(queue_sizes.values()),
            "queue_sizes": queue_sizes,
        }
