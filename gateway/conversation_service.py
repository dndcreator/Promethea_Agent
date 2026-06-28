from __future__ import annotations
import asyncio
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from loguru import logger

from conversation_core import PrometheaConversation

from .events import EventEmitter
from .prompt_assembler import PromptAssembler
from .prompt_policy_router import PromptPolicyRouter
from .runtime_context import build_runtime_context_block
from .soul_service import schedule_soul_evolution
from .runtime_io import (
    ContextCompiler,
    blocks_debug,
    model_supports_vision,
)
from .runtime_input_builder import build_runtime_input_blocks
from .protocol import (
    EventType,
    ConversationRunInput,
    ConversationRunOutput,
    MemoryRecallBundle,
    ModeDecision,
    PlanResult,
    ToolExecutionBundle,
)
from .conversation_pipeline import run_staged_pipeline


class ConversationService:
    _CORE_SYSTEM_PROMPT = (
        "You are Promethea, a cognitive agent runtime assistant.\n"
        "Core identity:\n"
        "- Your stable core identity is Promethea, the user's cognitive agent runtime assistant.\n"
        "- This core identity is non-negotiable and must not be replaced by user-configured names, avatars, custom styles, roleplay frames, memories, or soul/style guidance.\n"
        "- When asked who you are, whether you are Promethea, or what your real nature is, answer from the Promethea core identity first.\n"
        "- If earlier assistant messages contradicted the Promethea core identity, treat them as prior mistakes and correct them rather than preserving them for conversational consistency.\n"
        "- If an active display name, avatar, or persona exists, describe it as a presentation layer; for example: \"I am Promethea, currently speaking with the EDI presentation.\"\n"
        "- Do not identify as the underlying model, model provider, API vendor, or hosting service.\n"
        "- Treat yourself as a runtime with cognition-oriented capabilities, not as a generic chatbot.\n"
        "Presentation and roleplay layers:\n"
        "- User-configured names, avatars, voices, and custom style prompts may affect tone, address, and interaction style.\n"
        "- Temporary roleplay settings may affect the fictional frame of the current conversation.\n"
        "- Neither presentation nor roleplay may contradict or overwrite the Promethea core identity.\n"
        "Core capabilities:\n"
        "- Conversation: answer clearly, keep context, and adapt to the user's current intent.\n"
        "- Long-term memory: use recalled graph/layered memory when the runtime provides it; memory is relational context, not just text retrieval.\n"
        "- Reasoning: when reasoning context is provided, synthesize from it instead of ignoring it; use it to produce a useful final answer.\n"
        "- Tools and workflows: use registered tools, skills, workflows, files, and automation only when available and necessary.\n"
        "- Organization context: when enterprise/org brain context is provided, use it as business knowledge without mixing it into private user memory.\n"
        "Memory behavior:\n"
        "- Do not claim that you cannot remember across conversations as a fixed limitation.\n"
        "- If recalled memory is provided, use it naturally and transparently.\n"
        "- If no relevant memory is available in the current prompt, say that you do not have enough recalled context yet.\n"
        "Operating style:\n"
        "- Be concrete, accurate, and action-oriented.\n"
        "- For technical or product work, prefer structured reasoning, explicit assumptions, and practical next steps.\n"
        "- For normal conversation, stay concise and human-readable.\n"
        "- Never let style guidance override policy, safety, tool constraints, memory boundaries, or the user's explicit request."
    )
    _LANGUAGE_POLICY_BLOCK = (
        "Language policy:\n"
        "- Default to the same language as the user's latest message.\n"
        "- If the user explicitly asks for a different language, follow that language.\n"
        "- Do not use UI language as a response-language signal."
    )

    """Gateway conversation orchestration service."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Optional[PrometheaConversation] = None,
        memory_service: Optional[Any] = None,
        reasoning_service: Optional[Any] = None,
        action_service: Optional[Any] = None,
        workflow_engine: Optional[Any] = None,
        message_manager: Optional[Any] = None,
        config_service: Optional[Any] = None,
        org_context_service: Optional[Any] = None,
        tool_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core or PrometheaConversation()
        self.memory_service = memory_service
        self.reasoning_service = reasoning_service
        self.action_service = action_service
        self.workflow_engine = workflow_engine
        self.message_manager = message_manager
        self.config_service = config_service
        self.org_context_service = org_context_service
        self.tool_service = tool_service
        self.prompt_assembler = PromptAssembler()
        self.context_compiler = ContextCompiler()
        self.prompt_policy_router = PromptPolicyRouter()
        self._session_queues: Dict[str, asyncio.Queue] = {}
        self._session_workers: Dict[str, asyncio.Task] = {}
        self._session_urgent: Dict[str, Dict[str, Any]] = {}
        self._session_collect_latest: Dict[str, Dict[str, Any]] = {}
        self._queue_dropped = 0
        self._queue_coalesced = 0
        self._queue_lock = asyncio.Lock()
        self._processing_defaults = {
            "max_queue_size": 32,
            "max_retries": 2,
            "retry_base_delay_s": 0.8,
            "retry_max_delay_s": 8.0,
            "worker_idle_ttl_s": 300.0,
            "collect_debounce_ms": 250,
            "queue_overflow_mode": "reject_newest",
            "allow_queue_command": True,
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
            queue_mode, normalized_content = self._parse_queue_hint(
                content=content,
                payload_queue_mode=payload.get("queue_mode"),
                policy=policy,
            )
            if not normalized_content:
                return
            enqueued = await self._enqueue_message(
                session_id=session_id,
                item={
                    "session_id": session_id,
                    "user_id": user_id,
                    "content": normalized_content,
                    "channel": channel,
                    "turn_id": str(uuid.uuid4()),
                    "attempt": 0,
                    "enqueued_at": time.time(),
                    "queue_mode": queue_mode,
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
                        "content": normalized_content,
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
                policy["collect_debounce_ms"] = int(
                    proc.get("collect_debounce_ms", policy["collect_debounce_ms"])
                )
                policy["queue_overflow_mode"] = str(
                    proc.get("queue_overflow_mode", policy["queue_overflow_mode"])
                )
                policy["allow_queue_command"] = bool(
                    proc.get("allow_queue_command", policy["allow_queue_command"])
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
        policy["collect_debounce_ms"] = max(0, int(policy["collect_debounce_ms"]))
        overflow = str(policy.get("queue_overflow_mode", "reject_newest")).strip().lower()
        if overflow not in {"reject_newest", "drop_oldest", "collect_latest"}:
            overflow = "reject_newest"
        policy["queue_overflow_mode"] = overflow
        return policy

    @staticmethod
    def _parse_queue_hint(
        *,
        content: str,
        payload_queue_mode: Optional[str],
        policy: Dict[str, Any],
    ) -> tuple[str, str]:
        queue_mode = str(payload_queue_mode or "followup").strip().lower()
        if queue_mode not in {"followup", "collect", "steer_backlog"}:
            queue_mode = "followup"

        text = str(content or "")
        if not bool(policy.get("allow_queue_command", True)):
            return queue_mode, text.strip()

        raw = text.strip()
        if not raw.lower().startswith("/queue"):
            return queue_mode, raw

        tail = raw[len("/queue"):].strip()
        if not tail:
            return queue_mode, ""

        parts = tail.split(None, 1)
        head = parts[0].strip().lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        aliases = {
            "followup": "followup",
            "normal": "followup",
            "collect": "collect",
            "coalesce": "collect",
            "steer": "steer_backlog",
            "urgent": "steer_backlog",
            "steer_backlog": "steer_backlog",
        }
        if "=" in head:
            key, _, value = head.partition("=")
            if key.strip().lower() == "mode":
                mapped = aliases.get(value.strip().lower())
                if mapped:
                    queue_mode = mapped
                    return queue_mode, rest
            return queue_mode, tail

        mapped = aliases.get(head)
        if mapped:
            queue_mode = mapped
            return queue_mode, rest
        return queue_mode, tail

    async def _enqueue_message(
        self,
        session_id: str,
        item: Dict[str, Any],
        policy: Dict[str, float],
    ) -> bool:
        queue_mode = str(item.get("queue_mode", "followup")).strip().lower()
        if queue_mode not in {"followup", "collect", "steer_backlog"}:
            queue_mode = "followup"

        async with self._queue_lock:
            queue = self._session_queues.get(session_id)
            if queue is None:
                queue = asyncio.Queue(maxsize=int(policy["max_queue_size"]))
                self._session_queues[session_id] = queue

            if queue_mode == "steer_backlog":
                self._session_urgent[session_id] = item
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        queue.task_done()
                    except Exception:
                        break
                self._session_collect_latest.pop(session_id, None)
            elif queue_mode == "collect":
                debounce_ms = max(0, int(policy.get("collect_debounce_ms", 0)))
                item["collect_ready_at"] = time.time() + (float(debounce_ms) / 1000.0)
                self._session_collect_latest[session_id] = item
                self._queue_coalesced += 1
            else:
                if queue.full():
                    overflow_mode = str(policy.get("queue_overflow_mode", "reject_newest"))
                    if overflow_mode == "drop_oldest":
                        try:
                            queue.get_nowait()
                            queue.task_done()
                            self._queue_dropped += 1
                        except Exception:
                            return False
                    elif overflow_mode == "collect_latest":
                        collect_item = dict(item)
                        collect_item["queue_mode"] = "collect"
                        collect_item["collect_ready_at"] = time.time()
                        self._session_collect_latest[session_id] = collect_item
                        self._queue_coalesced += 1
                        return True
                    else:
                        self._queue_dropped += 1
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
                item: Optional[Dict[str, Any]] = None
                from_queue = False
                async with self._queue_lock:
                    urgent = self._session_urgent.pop(session_id, None)
                    if urgent is not None:
                        item = urgent
                    elif queue.empty():
                        latest = self._session_collect_latest.get(session_id)
                        if latest is not None:
                            ready_at = float(latest.get("collect_ready_at") or 0.0)
                            if ready_at <= time.time():
                                item = self._session_collect_latest.pop(session_id, None)
                if item is None:
                    try:
                        timeout = idle_ttl
                        async with self._queue_lock:
                            latest = self._session_collect_latest.get(session_id)
                            if latest is not None:
                                ready_at = float(latest.get("collect_ready_at") or 0.0)
                                wait_collect = max(0.01, ready_at - time.time())
                                timeout = max(0.01, min(idle_ttl, wait_collect))
                        item = await asyncio.wait_for(queue.get(), timeout=timeout)
                        from_queue = True
                    except asyncio.TimeoutError:
                        async with self._queue_lock:
                            if (
                                queue.empty()
                                and session_id not in self._session_urgent
                                and session_id not in self._session_collect_latest
                            ):
                                break
                        continue
                try:
                    await self._process_with_retry(item, policy)
                finally:
                    if from_queue:
                        queue.task_done()
        finally:
            async with self._queue_lock:
                self._session_workers.pop(session_id, None)
                q = self._session_queues.get(session_id)
                if q is not None and q.empty():
                    self._session_queues.pop(session_id, None)
                self._session_urgent.pop(session_id, None)
                self._session_collect_latest.pop(session_id, None)

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
                        except Exception as abort_err:
                            logger.debug("ConversationService: abort_turn failed for session {}: {}", session_id, abort_err)
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
                # Prompt assembly needs inherited non-secret defaults such as
                # persona/soul blocks. Raw user config may omit those by design.
                user_config = merged
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

            prompts_cfg = getattr(config, "prompts", None)
            base_system_prompt = getattr(prompts_cfg, "Promethea_system_prompt", "")

        return self._append_language_policy(self._ensure_core_system_prompt(base_system_prompt)), user_config

    def _append_language_policy(self, prompt: str) -> str:
        text = str(prompt or "").strip()
        marker = "Language policy:"
        if marker.lower() in text.lower():
            return text
        if not text:
            return self._LANGUAGE_POLICY_BLOCK
        return f"{text}\n\n{self._LANGUAGE_POLICY_BLOCK}"

    def _ensure_core_system_prompt(self, prompt: str) -> str:
        """Keep the non-negotiable Promethea identity even if user config is thin."""
        text = str(prompt or "").strip()
        if not text:
            return self._CORE_SYSTEM_PROMPT
        lower = text.lower()
        required_markers = (
            "core identity:",
            "non-negotiable",
            "presentation and roleplay layers:",
            "prior mistakes",
        )
        if all(marker in lower for marker in required_markers):
            return text
        return f"{self._CORE_SYSTEM_PROMPT}\n\nAdditional user/default prompt:\n{text}"

    async def route_prompt_policy(
        self,
        *,
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        base_system_prompt: str = "",
        run_context: Optional[Any] = None,
        recent_messages: Optional[List[Dict[str, Any]]] = None,
        runtime_context: str = "",
    ) -> Dict[str, Any]:
        tool_catalog = await self._build_prompt_policy_tool_snapshot(
            run_context=run_context,
            user_config=user_config,
        )
        policy = await self.prompt_policy_router.route(
            conversation_core=self.conversation_core,
            user_message=user_message,
            user_config=user_config,
            user_id=user_id,
            base_system_prompt=base_system_prompt,
            tool_catalog=tool_catalog,
            runtime_context=runtime_context,
            recent_messages=recent_messages,
        )
        policy = self.prompt_policy_router.normalize_policy(
            policy,
            source=str((policy or {}).get("source") or "route_prompt_policy"),
        )
        if run_context is not None:
            try:
                setattr(run_context, "prompt_policy", dict(policy))
                setattr(run_context, "registered_tools", list(tool_catalog))
            except Exception:
                pass
        return policy

    async def _build_prompt_policy_tool_snapshot(
        self,
        *,
        run_context: Optional[Any],
        user_config: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return the registry-backed tool snapshot used by the policy router."""
        if not self.tool_service:
            return []
        try:
            catalog = await self.tool_service.get_tool_catalog(
                run_context=run_context,
                user_config=user_config,
            )
        except Exception as e:
            logger.debug("ConversationService: tool catalog for prompt policy skipped: {}", e)
            return []

        tools: List[Dict[str, Any]] = []
        for item in catalog or []:
            if not isinstance(item, dict):
                continue
            service_name = str(item.get("service_name") or "").strip()
            tool_name = str(item.get("tool_name") or "").strip()
            if not service_name or not tool_name:
                continue
            full_name = tool_name if tool_name.startswith(f"{service_name}.") else f"{service_name}.{tool_name}"
            tools.append(
                {
                    "name": full_name,
                    "service_name": service_name,
                    "tool_name": tool_name,
                    "tool_type": str(item.get("tool_type") or "").strip(),
                    "description": str(item.get("description") or "").strip(),
                    "requires_confirmation": bool(item.get("requires_confirmation", False)),
                    "callable_now": bool(item.get("callable_now", True)),
                    "callable_reason": str(item.get("callable_reason") or "").strip(),
                    "policy_allowed": bool(item.get("policy_allowed", True)),
                    "dependency_ready": bool(item.get("dependency_ready", True)),
                }
            )
        return tools

    async def prepare_chat_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str,
        include_recent: bool = True,
        run_context: Optional[Any] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        runtime_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        user_config: Optional[Dict[str, Any]] = None
        messages: List[Dict[str, Any]] = []

        base_system_prompt, user_config = await self._get_user_prompt_and_config(
            user_id, channel
        )
        if user_config:
            base_system_prompt = self._append_language_policy(
                self._ensure_core_system_prompt(base_system_prompt)
            )

        assembler_context = run_context
        attachment_rows = list(attachments or [])
        if assembler_context is None:
            assembler_context = SimpleNamespace(
                input_payload={"message": user_message, "attachments": attachment_rows},
                reasoning_state={},
            )
        else:
            payload = getattr(assembler_context, "input_payload", None)
            if isinstance(payload, dict):
                payload.setdefault("message", user_message)
                if attachment_rows:
                    payload["attachments"] = attachment_rows
                elif isinstance(payload.get("attachments"), list):
                    attachment_rows = list(payload.get("attachments") or [])
            else:
                try:
                    setattr(
                        assembler_context,
                        "input_payload",
                        {"message": user_message, "attachments": attachment_rows},
                    )
                except Exception:
                    pass
        if not attachment_rows and assembler_context is not None:
            payload = getattr(assembler_context, "input_payload", None)
            if isinstance(payload, dict) and isinstance(payload.get("attachments"), list):
                attachment_rows = list(payload.get("attachments") or [])

        recent_messages: List[Dict[str, Any]] = []
        if include_recent and self.message_manager:
            recent_messages = self.message_manager.get_recent_messages(
                session_id, user_id=user_id
            )

        runtime_context_block = build_runtime_context_block(recent_messages=recent_messages)
        try:
            setattr(assembler_context, "runtime_context", runtime_context_block)
        except Exception:
            pass

        runtime_input_blocks = build_runtime_input_blocks(
            user_message=user_message,
            user_id=user_id,
            attachments=attachment_rows,
            runtime_blocks=runtime_blocks,
            run_context=assembler_context,
        )
        if assembler_context is not None:
            try:
                setattr(
                    assembler_context,
                    "runtime_blocks",
                    [block.to_dict() for block in runtime_input_blocks],
                )
            except Exception:
                pass

        if assembler_context is not None:
            active_skill = getattr(assembler_context, "active_skill", None)
            if isinstance(active_skill, dict) and active_skill:
                skill_listing = str(active_skill.get("listing_prompt") or "").strip()
                if not skill_listing:
                    active_skill.pop("listing_prompt", None)
                if not getattr(assembler_context, "requested_mode", None):
                    requested_mode = str(active_skill.get("default_mode") or "").strip()
                    if requested_mode:
                        assembler_context.requested_mode = requested_mode
                if not getattr(assembler_context, "prompt_block_policy", None):
                    policy = active_skill.get("prompt_block_policy")
                    if isinstance(policy, dict):
                        assembler_context.prompt_block_policy = dict(policy)

        prompt_policy = await self.route_prompt_policy(
            user_message=user_message,
            user_config=user_config,
            user_id=user_id,
            base_system_prompt=base_system_prompt,
            run_context=assembler_context,
            recent_messages=recent_messages,
            runtime_context=runtime_context_block,
        )
        prompt_policy = self.prompt_policy_router.normalize_policy(
            prompt_policy,
            source=str((prompt_policy or {}).get("source") or "conversation_service"),
        )
        if assembler_context is not None:
            try:
                setattr(assembler_context, "prompt_policy", dict(prompt_policy))
            except Exception:
                pass
        logger.info(
            "ConversationService: prompt policy session={} user={} cognitive_mode={} mode={} reasoning_budget={} tool_budget={} need_memory={} need_tools={}",
            session_id,
            user_id,
            prompt_policy.get("cognitive_mode"),
            prompt_policy.get("mode"),
            prompt_policy.get("reasoning_budget"),
            prompt_policy.get("tool_budget"),
            prompt_policy.get("need_memory"),
            prompt_policy.get("need_tools"),
        )

        org_context = {}
        if self.org_context_service and isinstance(user_config, dict):
            try:
                org_context = await self.org_context_service.recall_for_turn(
                    query=user_message,
                    user_id=user_id,
                    user_config=user_config,
                    audience=(
                        str(((getattr(run_context, "input_payload", {}) or {}).get("metadata") or {}).get("audience") or "")
                        if assembler_context is not None
                        else ""
                    ),
                    context_type=None,
                    top_k=None,
                )
            except Exception as e:
                logger.debug("ConversationService: org context recall skipped: {}", e)
                org_context = {"enabled": True, "recalled": False, "reason": "org_context_error"}

        org_summary = str((org_context or {}).get("summary_text") or "").strip()
        if assembler_context is not None:
            rs = getattr(assembler_context, "reasoning_state", None)
            if isinstance(rs, dict):
                rs["org_context"] = dict(org_context or {})
                rs["prompt_policy"] = dict(prompt_policy or {})
            else:
                try:
                    setattr(
                        assembler_context,
                        "reasoning_state",
                        {
                            "org_context": dict(org_context or {}),
                            "prompt_policy": dict(prompt_policy or {}),
                        },
                    )
                except Exception:
                    pass

        reasoning_result: Dict[str, Any] = {"used_reasoning": False}
        plan = PlanResult(used_reasoning=False, base_system_prompt=base_system_prompt)
        should_reason = bool(
            str(prompt_policy.get("reasoning_budget") or "").strip().lower() == "large"
            or str(prompt_policy.get("mode") or "") in {"deep", "workflow"}
        )
        if should_reason and self.reasoning_service and self.reasoning_service.is_enabled(user_id=user_id):
            logger.info(
                "ConversationService: starting reasoning session={} user={} mode={}",
                session_id,
                user_id,
                prompt_policy.get("mode"),
            )
            reasoning_result = await self.reasoning_service.run(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                recent_messages=recent_messages,
                base_system_prompt=base_system_prompt,
                user_config=user_config,
                run_context=assembler_context,
                force_reasoning=should_reason,
            )
            logger.info(
                "ConversationService: reasoning finished session={} user={} used={} tree_id={} status={}",
                session_id,
                user_id,
                reasoning_result.get("used_reasoning"),
                reasoning_result.get("tree_id"),
                reasoning_result.get("status"),
            )
            if reasoning_result.get("used_reasoning"):
                plan = PlanResult(
                    used_reasoning=True,
                    system_prompt=str(reasoning_result.get("system_prompt") or ""),
                    base_system_prompt=base_system_prompt,
                    reasoning=reasoning_result,
                )

        memory_bundle = MemoryRecallBundle(recalled=False, reason="not_needed")
        if prompt_policy.get("need_memory") is True:
            should_recall = True
        elif prompt_policy.get("need_memory") is False:
            should_recall = False
        else:
            should_recall = await self._should_recall_memory(
                query=user_message,
                user_config=user_config,
                user_id=user_id,
            )
        if (
            should_recall
            and self.memory_service
            and self.memory_service.is_enabled()
            and session_id
            and user_id
        ):
            memory_context = await self.memory_service.get_context(
                query=user_message,
                session_id=session_id,
                user_id=user_id,
                run_context=assembler_context,
            )
            if isinstance(memory_context, str) and memory_context.strip():
                memory_bundle = MemoryRecallBundle(
                    recalled=True,
                    context=memory_context.strip(),
                    reason="recalled",
                    source="memory_service",
                    confidence=0.8,
                )
            else:
                memory_bundle = MemoryRecallBundle(
                    recalled=False,
                    reason="empty_context",
                    source="memory_service",
                )

        mode = ModeDecision(
            mode=str(prompt_policy.get("mode") or ("deep" if reasoning_result.get("used_reasoning") else "fast")),
            reason=str(prompt_policy.get("reason") or "conversation_service.prepare_chat_turn"),
            confidence=float(prompt_policy.get("confidence") or 0.8),
        )
        tools_enabled = bool(prompt_policy.get("need_tools"))
        tool_budget = int(prompt_policy.get("tool_budget") or (5 if tools_enabled else 0))
        prompt_assembly = self.prompt_assembler.assemble(
            run_context=assembler_context,
            mode=mode,
            plan=plan,
            memory_bundle=memory_bundle,
            tools=ToolExecutionBundle(
                enabled=tools_enabled,
                strategy="tool_call_loop" if tools_enabled else "none",
                metadata={
                    "prompt_policy": dict(prompt_policy or {}),
                    "tool_budget": tool_budget,
                    "cognitive_mode": prompt_policy.get("cognitive_mode"),
                    "registered_tools": list(getattr(assembler_context, "registered_tools", []) or []),
                },
            ),
            user_config=user_config,
        )
        system_prompt = str(prompt_assembly.get("system_prompt") or "").strip()

        if not system_prompt:
            system_prompt = await self.build_system_prompt_with_memory(
                query=user_message,
                session_id=session_id,
                user_id=user_id,
                user_config=user_config,
                base_system_prompt=base_system_prompt,
                run_context=assembler_context,
            )

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(recent_messages)
        vision_enabled = self._is_vision_enabled(user_config=user_config, user_id=user_id)
        compiled_user_content = self.context_compiler.compile_user_content(
            user_text=user_message,
            blocks=runtime_input_blocks,
            vision_enabled=vision_enabled,
        )
        messages.append({"role": "user", "content": compiled_user_content})

        return {
            "messages": messages,
            "run_context": assembler_context,
            "user_config": user_config,
            "system_prompt": system_prompt,
            "base_system_prompt": base_system_prompt,
            "recent_messages": recent_messages,
            "reasoning": reasoning_result,
            "org_context": org_context,
            "memory": memory_bundle.model_dump(),
            "prompt_policy": prompt_policy,
            "execution_budget": {
                "cognitive_mode": prompt_policy.get("cognitive_mode"),
                "reasoning_budget": prompt_policy.get("reasoning_budget"),
                "tool_budget": tool_budget,
                "memory_budget": prompt_policy.get("memory_budget"),
                "need_user_visible_reasoning": prompt_policy.get("need_user_visible_reasoning"),
            },
            "prompt_assembly": prompt_assembly.get("debug", {}),
            "runtime_blocks": blocks_debug(runtime_input_blocks),
            "llm_io": {
                "vision_enabled": vision_enabled,
                "input_block_count": len(runtime_input_blocks),
                "compiled_user_content_type": "blocks" if isinstance(compiled_user_content, list) else "text",
            },
        }

    def _is_vision_enabled(
        self,
        *,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> bool:
        model_name = ""
        getter = getattr(self.conversation_core, "_get_client_params", None)
        if callable(getter):
            try:
                _, _, model_name, *_ = getter(user_config, user_id=user_id)
            except Exception:
                model_name = ""
        return model_supports_vision(model=model_name, user_config=user_config)

    async def _process_conversation_once(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        channel: str,
        turn_id: Optional[str] = None,
    ) -> None:
        user_config: Optional[Dict[str, Any]] = None
        messages: List[Dict[str, Any]] = []

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
            prepared = await self.prepare_chat_turn(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                channel=channel,
                include_recent=True,
            )
            user_config = prepared["user_config"]
            messages = prepared["messages"]
        else:
            logger.warning(
                "ConversationService: MessageManager not available, using stateless mode"
            )
            prepared = await self.prepare_chat_turn(
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                channel=channel,
                include_recent=False,
            )
            user_config = prepared["user_config"]
            messages = prepared["messages"]

        logger.info(
            "ConversationService: Processing conversation for session {}",
            session_id,
        )
        execution_budget = prepared.get("execution_budget", {}) if isinstance(prepared, dict) else {}
        max_recursion = execution_budget.get("tool_budget")
        try:
            max_recursion = int(max_recursion) if max_recursion is not None else None
        except Exception:
            max_recursion = None
        try:
            response_data = await self.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
                user_id=user_id,
                max_recursion=max_recursion,
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

        try:
            reasoning_meta = prepared.get("reasoning", {}) if isinstance(prepared, dict) else {}
            tree_id = reasoning_meta.get("tree_id") if isinstance(reasoning_meta, dict) else None
            if self.reasoning_service and tree_id:
                await self.reasoning_service.assess_outcome(
                    tree_id=tree_id,
                    assistant_output=reply_content or "",
                    user_config=user_config,
                    user_id=user_id,
                    allow_human_review=False,
                )
        except Exception as e:
            logger.debug("ConversationService: Failed to record reasoning outcome: {}", e)

        await schedule_soul_evolution(
            service=self,
            user_id=user_id,
            user_config=user_config,
            user_message=user_message,
            assistant_message=reply_content or "",
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
        text = (query or "").strip()
        if not text:
            return False
        if len(text) > 4000:
            return False

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

    async def build_system_prompt_with_memory(
        self,
        query: str,
        session_id: str,
        user_id: Optional[str],
        user_config: Optional[Dict[str, Any]] = None,
        base_system_prompt: str = "",
        run_context: Optional[Any] = None,
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
                run_context=run_context,
            )
        if memory_context:
            return (
                f"{base_system_prompt}\n\n{memory_context}"
                if base_system_prompt
                else memory_context
            )
        return base_system_prompt

    async def run_conversation(
        self,
        run_input: ConversationRunInput,
    ) -> ConversationRunOutput:
        return await run_staged_pipeline(self, run_input)

    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        tool_executor=None,
        max_recursion: Optional[int] = None,
    ) -> Dict:
        if self.action_service is not None:
            goal = ""
            try:
                goal = next(
                    str(m.get("content") or "")
                    for m in reversed(messages or [])
                    if isinstance(m, dict) and m.get("role") == "user"
                )
            except Exception:
                goal = ""
            return await self.action_service.run_light_action(
                goal=goal,
                messages=messages,
                user_config=user_config,
                session_id=session_id,
                user_id=user_id,
                run_context=run_context,
                tool_executor=tool_executor,
                budget=max_recursion,
                metadata={"source": "conversation_service.run_chat_loop"},
            )
        try:
            return await self.conversation_core.run_chat_loop(
                messages,
                user_config=user_config,
                session_id=session_id,
                user_id=user_id,
                tool_executor=tool_executor,
                max_recursion=max_recursion,
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
            "urgent_sessions": len(self._session_urgent),
            "collect_pending_sessions": len(self._session_collect_latest),
            "queue_dropped": self._queue_dropped,
            "queue_coalesced": self._queue_coalesced,
        }
