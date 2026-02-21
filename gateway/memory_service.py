from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from core.services import get_memory_service

from .events import EventEmitter
from .protocol import EventType
from memory.session_scope import scoped_session_id
from memory.session_scope import user_node_id


class MemoryService:
    """
    Gateway memory facade.

    Design:
    - Passive listener of full-turn interaction events (`interaction.completed`)
    - Agent and memory writes are decoupled
    - LLM only identifies long-term state candidates
    - Final write decision is code-driven (dedupe / change detection)
    """

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        memory_adapter: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        config_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.memory_adapter = memory_adapter or get_memory_service()
        self.llm_client = llm_client
        self.config_service = config_service

        self._recent_write_keys: List[str] = []
        self._recent_write_index: set[str] = set()
        self._recent_write_limit = 2000

        if not self.memory_adapter:
            logger.warning(
                "MemoryService: Memory adapter not available, memory features disabled"
            )
            self.enabled = False
        else:
            self.enabled = bool(
                hasattr(self.memory_adapter, "is_enabled")
                and self.memory_adapter.is_enabled()
            )
            if self.enabled:
                logger.info("MemoryService: Memory adapter initialized and enabled")
            else:
                logger.info("MemoryService: Memory adapter available but disabled")

        self._refresh_thresholds()

        if self.event_emitter:
            self._subscribe_events()

    def _subscribe_events(self) -> None:
        if not self.event_emitter:
            return
        self.event_emitter.on(
            EventType.INTERACTION_COMPLETED, self._on_interaction_completed
        )
        self.event_emitter.on(EventType.CONFIG_CHANGED, self._on_config_changed)
        self.event_emitter.on(EventType.CONFIG_RELOADED, self._on_config_reloaded)
        logger.debug("MemoryService: Subscribed to event bus")

    async def _on_config_changed(self, event_msg) -> None:
        try:
            payload = event_msg.payload
            user_id = payload.get("user_id")
            changes = payload.get("changes", {})
            if "memory" in changes:
                logger.info(
                    "MemoryService: Memory config changed for user {}", user_id
                )
        except Exception as e:
            logger.error("MemoryService: Error handling config change: {}", e)

    async def _on_config_reloaded(self, event_msg) -> None:
        try:
            logger.info("MemoryService: Default config reloaded")
        except Exception as e:
            logger.error("MemoryService: Error handling config reload: {}", e)

    def _normalize_content(self, text: str) -> str:
        content = (text or "").strip().lower()
        content = re.sub(r"\s+", " ", content)
        return content

    def _refresh_thresholds(self, user_id: Optional[str] = None) -> None:
        self._dedupe_min_candidate_chars = 8
        self._recent_write_limit = 2000
        self._write_min_user_chars = 4
        self._write_min_assistant_chars_for_short_user = 20
        self._write_max_combined_chars = 8000
        try:
            if self.config_service:
                if user_id:
                    cfg = self.config_service.get_merged_config(user_id)
                else:
                    cfg = self.config_service.get_default_config().model_dump()
            else:
                from config import config as global_config
                cfg = global_config.model_dump()
            gating = cfg.get("memory", {}).get("gating", {})
            write_filter = gating.get("write_filter", {})
            dedupe = gating.get("dedupe", {})
            self._write_min_user_chars = int(
                write_filter.get("min_user_chars", self._write_min_user_chars)
            )
            self._write_min_assistant_chars_for_short_user = int(
                write_filter.get(
                    "min_assistant_chars_for_short_user",
                    self._write_min_assistant_chars_for_short_user,
                )
            )
            self._write_max_combined_chars = int(
                write_filter.get("max_combined_chars", self._write_max_combined_chars)
            )
            self._dedupe_min_candidate_chars = int(
                dedupe.get("min_candidate_chars", self._dedupe_min_candidate_chars)
            )
            self._recent_write_limit = int(
                dedupe.get("recent_write_cache_size", self._recent_write_limit)
            )
        except Exception:
            pass

    def _make_write_key(self, user_id: str, memory_type: str, content: str) -> str:
        normalized = self._normalize_content(content)
        raw = f"{user_id}|{memory_type}|{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _remember_write_key(self, write_key: str) -> None:
        if write_key in self._recent_write_index:
            return
        self._recent_write_index.add(write_key)
        self._recent_write_keys.append(write_key)
        if len(self._recent_write_keys) > self._recent_write_limit:
            old_key = self._recent_write_keys.pop(0)
            self._recent_write_index.discard(old_key)

    def _should_write_candidate(
        self,
        user_id: str,
        memory_type: str,
        content: str,
    ) -> bool:
        self._refresh_thresholds(user_id=user_id)
        normalized = self._normalize_content(content)
        if len(normalized) < self._dedupe_min_candidate_chars:
            return False

        key = self._make_write_key(user_id, memory_type, normalized)
        if key in self._recent_write_index:
            return False
        return True

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    def _extract_tokens(self, text: str) -> List[str]:
        cleaned = self._normalize_content(text)
        if not cleaned:
            return []
        # Keep CJK blocks and latin/digits as separate token groups.
        chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", cleaned)
        tokens: List[str] = []
        for chunk in chunks:
            if re.match(r"^[a-z0-9_]+$", chunk):
                tokens.extend([p for p in chunk.split("_") if p])
            else:
                tokens.append(chunk)
        return tokens

    def _build_semantic_keys(self, content: str, llm_keys: Optional[List[str]] = None) -> List[str]:
        keys: set[str] = set()
        if llm_keys:
            for k in llm_keys:
                norm = self._normalize_content(str(k))
                if norm:
                    keys.add(norm)

        tokens = self._extract_tokens(content)
        for token in tokens:
            # Keep potentially meaningful token as semantic space.
            if len(token) >= 2:
                keys.add(token)

        return sorted(keys)

    def _normalize_candidates(self, candidates: Any) -> List[Dict[str, Any]]:
        allowed_types = {
            "goal",
            "preference",
            "constraint",
            "identity",
            "project_state",
        }
        result: List[Dict[str, Any]] = []
        if not isinstance(candidates, list):
            return result

        for item in candidates:
            if not isinstance(item, dict):
                continue
            raw_type = str(item.get("type", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if raw_type not in allowed_types or not content:
                continue
            semantic_keys = self._build_semantic_keys(
                content=content,
                llm_keys=item.get("semantic_keys"),
            )
            result.append(
                {
                    "type": raw_type,
                    "content": content,
                    "semantic_keys": semantic_keys,
                }
            )
        return result

    def _heuristic_classify(
        self, user_input: str, assistant_output: str
    ) -> Dict[str, Any]:
        """
        Fallback path when LLM is unavailable.
        Conservative by default to avoid noisy writes.
        """
        text = f"{user_input}\n{assistant_output}".lower()
        hints = [
            ("preference", ["prefer", "like"]),
            ("constraint", ["must", "cannot", "deadline"]),
            ("goal", ["goal", "plan to"]),
            ("identity", ["i am", "my name is"]),
            ("project_state", ["project", "milestone", "release"]),
        ]
        for mem_type, tokens in hints:
            if any(token in text for token in tokens):
                return {
                    "has_long_term_state": True,
                    "candidates": [
                        {
                            "type": mem_type,
                            "content": user_input.strip(),
                            "semantic_keys": self._build_semantic_keys(user_input),
                        }
                    ],
                }
        return {"has_long_term_state": False, "candidates": []}

    def _get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self.config_service:
            return None
        try:
            return self.config_service.get_user_config(user_id)
        except Exception:
            return None

    def _get_merged_config(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            if self.config_service:
                if user_id:
                    return self.config_service.get_merged_config(user_id)
                return self.config_service.get_default_config().model_dump()
            from config import config as global_config
            return global_config.model_dump()
        except Exception:
            return None

    def _resolve_memory_api_for_user(self, user_id: str) -> Dict[str, str]:
        cfg = self._get_merged_config(user_id=user_id) or {}
        api_cfg = cfg.get("api", {})
        memory_api = cfg.get("memory", {}).get("api", {})
        use_main = bool(memory_api.get("use_main_api", True))

        if use_main:
            return {
                "api_key": api_cfg.get("api_key", ""),
                "base_url": api_cfg.get("base_url", ""),
                "model": api_cfg.get("model", ""),
            }

        return {
            "api_key": memory_api.get("api_key") or api_cfg.get("api_key", ""),
            "base_url": memory_api.get("base_url") or api_cfg.get("base_url", ""),
            "model": memory_api.get("model") or api_cfg.get("model", ""),
        }

    async def _call_memory_classifier_llm(
        self,
        user_id: str,
        prompt: str,
        query: str,
    ) -> Optional[str]:
        api = self._resolve_memory_api_for_user(user_id)
        model = api.get("model", "").strip()
        api_key = api.get("api_key", "").strip()
        base_url = api.get("base_url", "").strip()

        if not model:
            return None

        if self.llm_client:
            try:
                response = await self.llm_client.call_llm(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": query},
                    ],
                    user_config={
                        "api": {
                            "api_key": api_key,
                            "base_url": base_url,
                            "model": model,
                        }
                    },
                    user_id=user_id,
                )
                return (response or {}).get("content", "") or ""
            except Exception as e:
                logger.debug("MemoryService: shared llm client memory classify failed: {}", e)

        if not api_key or not base_url:
            return None

        try:
            from openai import OpenAI

            def _sync_call() -> str:
                client = OpenAI(api_key=api_key, base_url=base_url)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": query},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                return (resp.choices[0].message.content or "").strip()

            return await asyncio.to_thread(_sync_call)
        except Exception as e:
            logger.debug("MemoryService: dedicated memory classify client failed: {}", e)
            return None

    async def _classify_interaction(
        self,
        user_input: str,
        assistant_output: str,
        user_id: str,
    ) -> Dict[str, Any]:
        if not self._should_run_memory_llm(user_input, assistant_output, user_id=user_id):
            return {"has_long_term_state": False, "candidates": []}

        prompt = (
            "You are a strict memory classifier. Input is one completed interaction "
            "(user input + assistant output). Ignore tool logs and execution traces. "
            "Find only durable user or project state worth long-term memory.\n"
            "Allowed types: goal, preference, constraint, identity, project_state.\n"
            "Return strict JSON with this schema:\n"
            "{\"has_long_term_state\": true|false, "
            "\"candidates\": [{\"type\": \"...\", \"content\": \"...\", \"semantic_keys\": [\"...\"]}]}\n"
            "Rules:\n"
            "- If no durable state, return has_long_term_state=false and empty candidates.\n"
            "- Keep each content concise and factual.\n"
            "- semantic_keys should include cross-lingual equivalents when obvious (example: apple / 苹果).\n"
            "- semantic_keys should be lower-case normalized concepts, not long sentences.\n"
            "- Do not include temporary tool/output details."
        )
        query = (
            f"[USER_INPUT]\n{user_input}\n\n"
            f"[ASSISTANT_OUTPUT]\n{assistant_output}\n"
        )
        try:
            text = await self._call_memory_classifier_llm(user_id, prompt, query)
            if not text:
                return self._heuristic_classify(user_input, assistant_output)
            obj = self._extract_json(text)
            if not obj:
                return {"has_long_term_state": False, "candidates": []}

            has_state = bool(obj.get("has_long_term_state", False))
            candidates = self._normalize_candidates(obj.get("candidates", []))
            if not candidates:
                return {"has_long_term_state": False, "candidates": []}
            return {"has_long_term_state": has_state, "candidates": candidates}
        except Exception as e:
            logger.debug("MemoryService: LLM interaction classifier failed: {}", e)
            return self._heuristic_classify(user_input, assistant_output)

    def _should_run_memory_llm(
        self,
        user_input: str,
        assistant_output: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Fast code-level gate before invoking LLM for memory-write judgement.
        """
        user_text = (user_input or "").strip()
        assistant_text = (assistant_output or "").strip()
        self._refresh_thresholds(user_id=user_id)
        if not user_text:
            return False

        if len(user_text) < self._write_min_user_chars and len(assistant_text) < self._write_min_assistant_chars_for_short_user:
            return False

        joined = f"{user_text}\n{assistant_text}"
        if len(joined) > self._write_max_combined_chars:
            return False

        return True

    def _get_connector(self):
        try:
            if self.memory_adapter and getattr(self.memory_adapter, "hot_layer", None):
                return self.memory_adapter.hot_layer.connector
        except Exception:
            return None
        return None

    def _graph_memory_state_changed(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        semantic_keys: Optional[List[str]] = None,
    ) -> bool:
        """
        Decide if candidate is new/changed against graph memory.
        Returns True when we should write.
        """
        connector = self._get_connector()
        if not connector:
            return True

        normalized = self._normalize_content(content)
        try:
            # 1) Exact content duplicate check for the same user.
            exact_rows = connector.query(
                """
                MATCH (m:Message {user_id: $user_id, role: 'user'})
                WHERE toLower(trim(m.content)) = $norm_content
                RETURN m.id AS id
                LIMIT 1
                """,
                {"user_id": user_id, "norm_content": normalized},
            )
            if exact_rows:
                return False

            # 2) Semantic-level check by user-owned sessions and linked entities.
            # If equivalent semantic key exists with same content => duplicate.
            # If semantic key exists but content differs => considered state change (write).
            keys = semantic_keys or []
            if keys:
                semantic_rows = connector.query(
                    """
                    MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)<-[:PART_OF_SESSION]-(m:Message {role: 'user'})
                    MATCH (e:Entity)-[:FROM_MESSAGE]->(m)
                    WHERE e.content IN $keys
                    RETURN m.content AS content
                    ORDER BY m.created_at DESC
                    LIMIT 5
                    """,
                    {"user_node_id": user_node_id(user_id), "keys": keys},
                )
                for row in semantic_rows:
                    prev = self._normalize_content(str(row.get("content", "")))
                    if prev == normalized:
                        return False
                if semantic_rows:
                    return True

            # 3) No equivalent found in graph.
            return True
        except Exception as e:
            logger.debug(
                "MemoryService: Graph-level dedupe failed for type={}, fallback allow write: {}",
                memory_type,
                e,
            )
            return True

    async def _on_interaction_completed(self, event_msg) -> None:
        """
        Interaction-level write path.
        Unit of judgement is one full turn:
        - user_input
        - assistant_output
        """
        if not self.enabled or not self.memory_adapter:
            return

        try:
            payload = event_msg.payload
            session_id = payload.get("session_id")
            user_id = payload.get("user_id") or "default_user"
            channel = payload.get("channel")
            user_input = (payload.get("user_input") or "").strip()
            assistant_output = (payload.get("assistant_output") or "").strip()

            if not session_id or (not user_input and not assistant_output):
                return

            # Only user input + assistant output is considered here;
            # tool logs are intentionally excluded by event payload design.
            classification = await self._classify_interaction(
                user_input=user_input,
                assistant_output=assistant_output,
                user_id=user_id,
            )
            if not classification.get("has_long_term_state", False):
                return

            candidates = classification.get("candidates", [])
            saved_count = 0
            for item in candidates:
                memory_type = item["type"]
                content = item["content"]
                semantic_keys = item.get("semantic_keys", [])
                write_key = self._make_write_key(user_id, memory_type, content)
                if not self._should_write_candidate(user_id, memory_type, content):
                    continue
                if not self._graph_memory_state_changed(
                    user_id=user_id,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                ):
                    continue

                success = self.memory_adapter.add_message(
                    session_id=session_id,
                    role="user",
                    content=content,
                    user_id=user_id,
                    metadata={
                        "memory_type": memory_type,
                        "semantic_keys": semantic_keys,
                        "memory_source": "interaction.completed",
                    },
                )
                if not success:
                    continue

                self._remember_write_key(write_key)
                self.memory_adapter.on_message_saved(session_id, "user", user_id)
                saved_count += 1

                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.MEMORY_SAVED,
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "channel": channel,
                            "source": "interaction.completed",
                            "memory_type": memory_type,
                            "semantic_keys": semantic_keys,
                            "content_length": len(content),
                        },
                    )

            if saved_count:
                logger.info(
                    "MemoryService: Saved {} memory item(s) from interaction, session={}",
                    saved_count,
                    session_id,
                )
        except Exception as e:
            logger.error("MemoryService: Error handling interaction.completed: {}", e)

    # ===== Memory query API =====

    async def get_context(
        self,
        query: str,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        if not self.enabled or not self.memory_adapter:
            return ""

        try:
            context = self.memory_adapter.get_context(
                query=query,
                session_id=session_id,
                user_id=user_id or "default_user",
            )
            if self.event_emitter and context:
                await self.event_emitter.emit(
                    EventType.MEMORY_RECALLED,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "query": query,
                        "context_length": len(context),
                    },
                )
            return context
        except Exception as e:
            logger.error("MemoryService: Error getting context: {}", e)
            return ""

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or not self.memory_adapter:
            return False
        try:
            success = self.memory_adapter.add_message(
                session_id=session_id,
                role=role,
                content=content,
                user_id=user_id or "default_user",
                metadata=metadata,
            )
            if success:
                self.memory_adapter.on_message_saved(
                    session_id, role, user_id or "default_user"
                )
            return success
        except Exception as e:
            logger.error("MemoryService: Error adding message: {}", e)
            return False

    # ===== Memory maintenance API =====

    async def cluster_entities(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"concepts_created": 0, "total_concepts": 0, "concepts": []}

        try:
            from memory import create_warm_layer_manager

            if not self.memory_adapter.hot_layer:
                return {"concepts_created": 0, "total_concepts": 0, "concepts": []}

            scoped_sid = scoped_session_id(session_id, user_id or "default_user")
            warm_layer = create_warm_layer_manager(self.memory_adapter.hot_layer.connector)
            concepts_created = warm_layer.cluster_entities(scoped_sid)
            concepts = warm_layer.get_concepts(scoped_sid)

            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.MEMORY_CLUSTERED,
                    {
                        "session_id": session_id,
                        "memory_session_id": scoped_sid,
                        "user_id": user_id,
                        "concepts_created": concepts_created,
                        "total_concepts": len(concepts),
                    },
                )

            return {
                "concepts_created": concepts_created,
                "total_concepts": len(concepts),
                "concepts": concepts,
            }
        except Exception as e:
            logger.error("MemoryService: Error clustering entities: {}", e)
            return {"concepts_created": 0, "total_concepts": 0, "concepts": []}

    async def summarize_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        incremental: bool = False,
    ) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}

        try:
            from memory import create_cold_layer_manager

            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}

            scoped_sid = scoped_session_id(session_id, user_id or "default_user")
            cold_layer = create_cold_layer_manager(self.memory_adapter.hot_layer.connector)
            if not cold_layer.should_create_summary(scoped_sid):
                return {
                    "status": "skipped",
                    "message": "Not enough messages or summary exists",
                }

            if incremental:
                summary_id = cold_layer.create_incremental_summary(scoped_sid)
            else:
                summary_id = cold_layer.summarize_session(scoped_sid)

            summary = cold_layer.get_summary_by_id(summary_id) if summary_id else None

            if self.event_emitter and summary_id:
                await self.event_emitter.emit(
                    EventType.MEMORY_SUMMARIZED,
                    {
                        "session_id": session_id,
                        "memory_session_id": scoped_sid,
                        "user_id": user_id,
                        "summary_id": summary_id,
                        "incremental": incremental,
                    },
                )

            return {
                "session_id": session_id,
                "memory_session_id": scoped_sid,
                "summary_id": summary_id,
                "summary": summary,
            }
        except Exception as e:
            logger.error("MemoryService: Error summarizing session: {}", e)
            return {"status": "error", "message": str(e)}

    async def apply_decay(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}

        try:
            from memory import create_forgetting_manager

            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}

            scoped_sid = scoped_session_id(session_id, user_id or "default_user")
            forgetting_manager = create_forgetting_manager(
                self.memory_adapter.hot_layer.connector
            )
            return forgetting_manager.apply_time_decay(scoped_sid)
        except Exception as e:
            logger.error("MemoryService: Error applying decay: {}", e)
            return {"status": "error", "message": str(e)}

    async def cleanup_forgotten(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"status": "skipped", "message": "Memory system not enabled"}

        try:
            from memory import create_forgetting_manager

            if not self.memory_adapter.hot_layer:
                return {"status": "skipped", "message": "Hot layer not available"}

            scoped_sid = scoped_session_id(session_id, user_id or "default_user")
            forgetting_manager = create_forgetting_manager(
                self.memory_adapter.hot_layer.connector
            )
            return forgetting_manager.cleanup_forgotten(scoped_sid)
        except Exception as e:
            logger.error("MemoryService: Error cleaning up forgotten: {}", e)
            return {"status": "error", "message": str(e)}

    def is_enabled(self) -> bool:
        return self.enabled and self.memory_adapter is not None
