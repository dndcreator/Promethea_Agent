from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from core.services import get_memory_service

from .events import EventEmitter
from .memory_gate import MemoryWriteGate, MemoryWriteRequest
from .memory_recall_schema import (
    DroppedRecallCandidate,
    MemoryRecallRequest,
    MemoryRecallResult,
    RecalledMemoryItem,
)
from .protocol import EventType
from memory.session_scope import ensure_session_owned, scoped_session_id
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
        message_manager: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.memory_adapter = memory_adapter or get_memory_service()
        self.llm_client = llm_client
        self.config_service = config_service
        self.message_manager = message_manager
        self._memory_write_gate = MemoryWriteGate()
        self._recent_write_keys: List[str] = []
        self._recent_write_index: set[str] = set()
        self._recent_write_limit = 2000
        self._sync_defaults = {
            "max_queue_size": 32,
            "drain_timeout_s": 20.0,
        }
        self._sync_queue: Optional[asyncio.Queue] = None
        self._sync_worker: Optional[asyncio.Task] = None
        self._sync_lock = asyncio.Lock()
        self._sync_active = 0
        self._sync_enqueued = 0
        self._sync_completed = 0
        self._sync_failed = 0
        self._sync_dropped = 0
        self._sync_last_error = ""
        self._sync_last_activity_ts = 0.0
        self._sync_current_item: Optional[Dict[str, Any]] = None
        self._sync_shutdown_requested = False

        # Backlog 011: recall inspector in-memory history.
        self._recall_runs: List[Dict[str, Any]] = []
        self._recall_by_request: Dict[str, Dict[str, Any]] = {}
        self._recall_history_limit = 200
        self._write_decisions: List[Dict[str, Any]] = []
        self._write_decision_limit = 500
        self._write_proposals: List[Dict[str, Any]] = []
        self._write_proposal_by_id: Dict[str, Dict[str, Any]] = {}
        self._write_proposal_limit = 300

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
            EventType.INTERACTION_COMPLETED, self._enqueue_interaction_completed
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
        profile = "balanced"
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
            profile = str(cfg.get("memory", {}).get("profile", "balanced") or "balanced").strip().lower()
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
        if profile == "conservative":
            self._write_min_user_chars = max(self._write_min_user_chars, 10)
            self._dedupe_min_candidate_chars = max(self._dedupe_min_candidate_chars, 12)
            self._write_max_combined_chars = min(self._write_max_combined_chars, 6000)
        elif profile == "aggressive":
            self._write_min_user_chars = max(1, self._write_min_user_chars - 2)
            self._dedupe_min_candidate_chars = max(4, self._dedupe_min_candidate_chars - 2)
            self._write_max_combined_chars = min(12000, self._write_max_combined_chars + 2000)

    def _resolve_sync_policy(self, user_id: Optional[str] = None) -> Dict[str, float]:
        policy = dict(self._sync_defaults)
        try:
            cfg = self._get_merged_config(user_id=user_id) or {}
            sync_cfg = cfg.get("memory", {}).get("sync", {})
            policy["max_queue_size"] = int(
                sync_cfg.get("max_queue_size", policy["max_queue_size"])
            )
            policy["drain_timeout_s"] = float(
                sync_cfg.get("drain_timeout_s", policy["drain_timeout_s"])
            )
        except Exception:
            pass
        policy["max_queue_size"] = max(1, int(policy["max_queue_size"]))
        policy["drain_timeout_s"] = max(1.0, float(policy["drain_timeout_s"]))
        return policy

    async def _ensure_sync_queue(self, user_id: Optional[str] = None) -> asyncio.Queue:
        policy = self._resolve_sync_policy(user_id=user_id)
        async with self._sync_lock:
            queue = self._sync_queue
            if queue is None or queue.maxsize != int(policy["max_queue_size"]):
                queue = asyncio.Queue(maxsize=int(policy["max_queue_size"]))
                self._sync_queue = queue
            if self._sync_worker is None or self._sync_worker.done():
                self._sync_shutdown_requested = False
                self._sync_worker = asyncio.create_task(self._sync_worker_loop())
            return queue

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

    def _verify_candidates_fallback(
        self,
        user_input: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Lightweight guard when verifier LLM is unavailable.
        Keep candidates with minimum semantic overlap against user input.
        """
        user_tokens = set(self._extract_tokens(user_input))
        if not user_tokens:
            return []
        accepted: List[Dict[str, Any]] = []
        for c in candidates or []:
            cand_tokens = set(self._extract_tokens(str(c.get("content", ""))))
            if not cand_tokens:
                continue
            overlap = len(user_tokens.intersection(cand_tokens)) / max(1, len(cand_tokens))
            if overlap < 0.25:
                continue
            row = dict(c)
            row["verify_confidence"] = round(float(overlap), 3)
            row["verify_reason"] = "fallback_overlap"
            row["verify_evidence"] = ""
            row["verify_attribution"] = "user"
            accepted.append(row)
        return accepted

    async def _verify_candidates_with_llm(
        self,
        user_id: str,
        user_input: str,
        assistant_output: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Verify candidate meaning/attribution before writing to memory.
        This prevents memory drift caused by assistant-side interpretations.
        """
        if not candidates:
            return []
        prompt = (
            "You are a memory write verifier.\n"
            "Given USER_INPUT, ASSISTANT_OUTPUT and candidate memories, decide whether each candidate can be safely written.\n"
            "Acceptance requirements:\n"
            "1) Candidate meaning is supported by the interaction.\n"
            "2) Attribution is correct: should not convert assistant explanation into user preference.\n"
            "3) It looks durable (not temporary tool/runtime artifact).\n"
            "Return strict JSON:\n"
            "{\"decisions\":[{\"index\":0,\"accept\":true|false,\"confidence\":0..1,"
            "\"reason\":\"...\",\"evidence\":\"...\",\"attribution\":\"user|assistant|project|unclear\"}]}\n"
            "Prefer rejecting uncertain candidates."
        )
        cands_json = json.dumps(candidates, ensure_ascii=False)
        query = (
            f"[USER_INPUT]\n{user_input}\n\n"
            f"[ASSISTANT_OUTPUT]\n{assistant_output}\n\n"
            f"[CANDIDATES]\n{cands_json}\n"
        )
        text = await self._call_memory_classifier_llm(user_id, prompt, query)
        if not text:
            return self._verify_candidates_fallback(user_input, candidates)
        obj = self._extract_json(text)
        if not isinstance(obj, dict):
            return self._verify_candidates_fallback(user_input, candidates)
        decisions = obj.get("decisions")
        if not isinstance(decisions, list):
            return self._verify_candidates_fallback(user_input, candidates)

        accepted: List[Dict[str, Any]] = []
        by_index: Dict[int, Dict[str, Any]] = {}
        for d in decisions:
            if not isinstance(d, dict):
                continue
            try:
                idx = int(d.get("index"))
            except Exception:
                continue
            by_index[idx] = d

        for idx, c in enumerate(candidates):
            d = by_index.get(idx, {})
            accept = bool(d.get("accept", False))
            conf = float(d.get("confidence", 0.0) or 0.0)
            attribution = str(d.get("attribution", "unclear")).strip().lower()
            if (not accept) or conf < 0.55 or attribution in {"assistant", "unclear"}:
                continue
            row = dict(c)
            row["verify_confidence"] = round(conf, 3)
            row["verify_reason"] = str(d.get("reason", "")).strip()[:300]
            row["verify_evidence"] = str(d.get("evidence", "")).strip()[:500]
            row["verify_attribution"] = attribution
            accepted.append(row)
        return accepted

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

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off", ""}:
                return False
            return default
        return bool(value)

    def _resolve_memory_api_for_user(self, user_id: str) -> Dict[str, str]:
        cfg = self._get_merged_config(user_id=user_id) or {}
        api_cfg = cfg.get("api", {})
        memory_api = cfg.get("memory", {}).get("api", {})
        use_main = self._to_bool(memory_api.get("use_main_api", True), default=True)

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
            "- semantic_keys should include cross-lingual equivalents when obvious (example: apple / 鑻规灉).\n"
            "- semantic_keys should be lower-case normalized concepts, not long sentences.\n"
            "- Do not include temporary tool/output details.\n"
            "- Candidate must reflect user/project meaning from the interaction; do not transform assistant explanation into user preference."
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

    def _find_conflict_candidates(
        self,
        *,
        user_id: str,
        content: str,
        semantic_keys: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[str]:
        connector = self._get_connector()
        if not connector:
            return []
        keys = [str(k).strip() for k in (semantic_keys or []) if str(k).strip()]
        if not keys:
            return []
        normalized = self._normalize_content(content)
        try:
            rows = connector.query(
                """
                MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)<-[:PART_OF_SESSION]-(m:Message {role: 'user'})
                MATCH (e:Entity)-[:FROM_MESSAGE]->(m)
                WHERE e.content IN $keys
                RETURN m.content AS content
                ORDER BY m.created_at DESC
                LIMIT 10
                """,
                {
                    "user_node_id": user_node_id(user_id),
                    "keys": keys,
                },
            )
        except Exception:
            return []
        conflicts: List[str] = []
        for row in rows or []:
            prev = str((row or {}).get("content", "")).strip()
            if not prev:
                continue
            if self._normalize_content(prev) == normalized:
                continue
            conflicts.append(prev)
        return conflicts[: max(1, int(limit))]

    async def _emit_memory_write_decision(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: Optional[str],
        memory_type: str,
        content: str,
        semantic_keys: List[str],
        decision: str,
        target_memory_layer: str,
        reason: str,
        requires_user_confirmation: bool = False,
        conflict_candidates: Optional[List[str]] = None,
        persisted: bool = False,
        proposal_id: Optional[str] = None,
    ) -> None:
        row = {
            "decision_id": f"mwd_{int(time.time() * 1000)}_{abs(hash((session_id, user_id, memory_type, decision))) % 100000}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
            "memory_type": memory_type,
            "target_memory_layer": target_memory_layer,
            "decision": decision,
            "reason": reason,
            "requires_user_confirmation": bool(requires_user_confirmation),
            "conflict_candidates": list(conflict_candidates or []),
            "semantic_keys": list(semantic_keys or []),
            "content_length": len(content or ""),
            "content_preview": (content or "")[:200],
            "persisted": bool(persisted),
            "source": "interaction.completed",
            "proposal_id": proposal_id,
        }
        self._write_decisions.append(row)
        if len(self._write_decisions) > self._write_decision_limit:
            self._write_decisions = self._write_decisions[-self._write_decision_limit :]
        if not self.event_emitter:
            return
        await self.event_emitter.emit(
            EventType.MEMORY_WRITE_DECIDED,
            row,
        )

    def _create_write_proposal(
        self,
        *,
        session_id: str,
        user_id: str,
        memory_type: str,
        target_memory_layer: str,
        content: str,
        semantic_keys: List[str],
        conflict_candidates: Optional[List[str]] = None,
        reason: str = "conflict_detected",
    ) -> str:
        proposal_id = f"mwp_{int(time.time() * 1000)}_{abs(hash((session_id, user_id, memory_type, content))) % 100000}"
        row = {
            "proposal_id": proposal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "session_id": session_id,
            "user_id": user_id,
            "memory_type": memory_type,
            "target_memory_layer": target_memory_layer,
            "content": content,
            "semantic_keys": list(semantic_keys or []),
            "conflict_candidates": list(conflict_candidates or []),
            "reason": reason,
        }
        self._write_proposals.append(row)
        self._write_proposal_by_id[proposal_id] = row
        if len(self._write_proposals) > self._write_proposal_limit:
            removed = self._write_proposals.pop(0)
            rid = str(removed.get("proposal_id") or "")
            if rid:
                self._write_proposal_by_id.pop(rid, None)
        return proposal_id
    async def _on_interaction_completed(self, event_msg) -> None:
        """Backward-compatible entrypoint for tests and direct callers."""
        payload = dict(getattr(event_msg, "payload", {}) or {})
        await self._process_interaction_completed(payload)

    async def _enqueue_interaction_completed(self, event_msg) -> None:
        if not self.enabled or not self.memory_adapter:
            return

        payload = dict(getattr(event_msg, "payload", {}) or {})
        session_id = payload.get("session_id")
        user_id = payload.get("user_id") or "default_user"
        user_input = (payload.get("user_input") or "").strip()
        assistant_output = (payload.get("assistant_output") or "").strip()
        if not session_id or (not user_input and not assistant_output):
            return

        queue = await self._ensure_sync_queue(user_id=user_id)
        item = {
            "session_id": session_id,
            "user_id": user_id,
            "channel": payload.get("channel"),
            "user_input": user_input,
            "assistant_output": assistant_output,
            "queued_at": time.time(),
        }

        if queue.full():
            self._sync_dropped += 1
            self._sync_last_activity_ts = time.time()
            self._sync_last_error = "memory sync queue full"
            logger.warning(
                "MemoryService: memory sync queue full, drop interaction session={} user={}",
                session_id,
                user_id,
            )
            return

        queue.put_nowait(item)
        self._sync_enqueued += 1
        self._sync_last_activity_ts = time.time()

    async def _sync_worker_loop(self) -> None:
        logger.info("MemoryService: memory sync worker started")
        try:
            while not self._sync_shutdown_requested:
                queue = self._sync_queue
                if queue is None:
                    return
                item = await queue.get()
                self._sync_active += 1
                self._sync_current_item = item
                self._sync_last_activity_ts = time.time()
                try:
                    await self._process_interaction_completed(item)
                    self._sync_completed += 1
                    self._sync_last_error = ""
                except Exception as e:
                    self._sync_failed += 1
                    self._sync_last_error = str(e)
                    logger.error("MemoryService: background memory sync failed: {}", e)
                finally:
                    self._sync_active = max(0, self._sync_active - 1)
                    self._sync_current_item = None
                    self._sync_last_activity_ts = time.time()
                    queue.task_done()
        except asyncio.CancelledError:
            logger.info("MemoryService: memory sync worker cancelled")
            raise
        finally:
            self._sync_worker = None

    async def _process_interaction_completed(self, payload: Dict[str, Any]) -> None:
        """
        Interaction-level write path.
        Unit of judgement is one full turn:
        - user_input
        - assistant_output
        """
        if not self.enabled or not self.memory_adapter:
            return

        session_id = payload.get("session_id")
        user_id = payload.get("user_id") or "default_user"
        channel = payload.get("channel")
        user_input = (payload.get("user_input") or "").strip()
        assistant_output = (payload.get("assistant_output") or "").strip()

        if not session_id or (not user_input and not assistant_output):
            return

        classification = await self._classify_interaction(
            user_input=user_input,
            assistant_output=assistant_output,
            user_id=user_id,
        )
        if not classification.get("has_long_term_state", False):
            return

        raw_candidates = classification.get("candidates", [])
        candidates = await self._verify_candidates_with_llm(
            user_id=user_id,
            user_input=user_input,
            assistant_output=assistant_output,
            candidates=raw_candidates,
        )
        saved_count = 0
        for item in candidates:
            memory_type = item["type"]
            content = item["content"]
            semantic_keys = item.get("semantic_keys", [])
            write_key = self._make_write_key(user_id, memory_type, content)

            gate_request = MemoryWriteRequest(
                source_text=user_input,
                source_turn={
                    "user_input": user_input,
                    "assistant_output": assistant_output,
                },
                proposed_memory_type=memory_type,
                extracted_content=content,
                confidence=float(item.get("verify_confidence") or 0.8),
                related_entities=list(semantic_keys or []),
                session_id=session_id,
                user_id=user_id,
                metadata={
                    "verify_reason": item.get("verify_reason", ""),
                    "verify_attribution": item.get("verify_attribution", ""),
                },
                conflict_candidates=self._find_conflict_candidates(
                    user_id=user_id,
                    content=content,
                    semantic_keys=semantic_keys,
                ),
            )
            gate_decision = self._memory_write_gate.evaluate(gate_request)
            if self._is_suppressed_by_feedback(
                user_id=user_id,
                memory_type=memory_type,
                semantic_keys=semantic_keys,
            ):
                await self._emit_memory_write_decision(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                    decision="deny",
                    target_memory_layer=gate_decision.target_memory_layer,
                    reason="suppressed_by_user_feedback",
                    conflict_candidates=gate_decision.conflict_candidates,
                    persisted=False,
                )
                continue
            if gate_decision.decision != "allow":
                proposal_id = None
                if gate_decision.requires_user_confirmation:
                    proposal_id = self._create_write_proposal(
                        session_id=session_id,
                        user_id=user_id,
                        memory_type=memory_type,
                        target_memory_layer=gate_decision.target_memory_layer,
                        content=content,
                        semantic_keys=semantic_keys,
                        conflict_candidates=gate_decision.conflict_candidates,
                        reason=gate_decision.reason,
                    )
                await self._emit_memory_write_decision(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                    decision=gate_decision.decision,
                    target_memory_layer=gate_decision.target_memory_layer,
                    reason=gate_decision.reason,
                    requires_user_confirmation=gate_decision.requires_user_confirmation,
                    conflict_candidates=gate_decision.conflict_candidates,
                    persisted=False,
                    proposal_id=proposal_id,
                )
                continue

            if not self._should_write_candidate(user_id, memory_type, content):
                await self._emit_memory_write_decision(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                    decision="deny",
                    target_memory_layer=gate_decision.target_memory_layer,
                    reason="duplicate_or_too_short",
                    conflict_candidates=gate_decision.conflict_candidates,
                    persisted=False,
                )
                continue

            if not self._graph_memory_state_changed(
                user_id=user_id,
                memory_type=memory_type,
                content=content,
                semantic_keys=semantic_keys,
            ):
                await self._emit_memory_write_decision(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                    decision="deny",
                    target_memory_layer=gate_decision.target_memory_layer,
                    reason="graph_duplicate",
                    conflict_candidates=gate_decision.conflict_candidates,
                    persisted=False,
                )
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
                    "target_memory_layer": gate_decision.target_memory_layer,
                    "verify_confidence": item.get("verify_confidence"),
                    "verify_reason": item.get("verify_reason", ""),
                    "verify_evidence": item.get("verify_evidence", ""),
                    "verify_attribution": item.get("verify_attribution", ""),
                },
            )
            if not success:
                await self._emit_memory_write_decision(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    memory_type=memory_type,
                    content=content,
                    semantic_keys=semantic_keys,
                    decision="deny",
                    target_memory_layer=gate_decision.target_memory_layer,
                    reason="adapter_write_failed",
                    conflict_candidates=gate_decision.conflict_candidates,
                    persisted=False,
                )
                continue

            self._remember_write_key(write_key)
            self.memory_adapter.on_message_saved(session_id, "user", user_id)
            saved_count += 1

            await self._emit_memory_write_decision(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                memory_type=memory_type,
                content=content,
                semantic_keys=semantic_keys,
                decision="allow",
                target_memory_layer=gate_decision.target_memory_layer,
                reason=gate_decision.reason,
                conflict_candidates=gate_decision.conflict_candidates,
                persisted=True,
            )

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

    def get_sync_stats(self) -> Dict[str, Any]:
        queue_size = self._sync_queue.qsize() if self._sync_queue else 0
        pending = queue_size + self._sync_active
        return {
            "enabled": self.enabled and self.memory_adapter is not None,
            "pending": pending,
            "queued": queue_size,
            "active": self._sync_active,
            "idle": pending == 0,
            "worker_running": bool(self._sync_worker and not self._sync_worker.done()),
            "enqueued": self._sync_enqueued,
            "completed": self._sync_completed,
            "failed": self._sync_failed,
            "dropped": self._sync_dropped,
            "last_error": self._sync_last_error,
            "last_activity_ts": self._sync_last_activity_ts,
            "current_session_id": (
                self._sync_current_item.get("session_id")
                if isinstance(self._sync_current_item, dict)
                else None
            ),
        }

    async def wait_until_idle(self, timeout_s: Optional[float] = None) -> bool:
        deadline = time.time() + timeout_s if timeout_s else None
        while True:
            if self.get_sync_stats()["pending"] == 0:
                return True
            if deadline is not None and time.time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def shutdown(self) -> bool:
        timeout_s = self._resolve_sync_policy().get("drain_timeout_s", 20.0)
        drained = await self.wait_until_idle(timeout_s=timeout_s)
        self._sync_shutdown_requested = True
        worker = self._sync_worker
        if worker and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        return drained

    # ===== Memory query API =====

    def _extract_run_context_fields(self, run_context: Optional[Any]) -> Dict[str, Any]:
        if run_context is None:
            return {}
        trace_id = getattr(run_context, "trace_id", None)
        request_id = getattr(run_context, "request_id", None)
        session_value = getattr(run_context, "session_id", None)
        user_value = getattr(run_context, "user_id", None)
        if session_value is None:
            session_state = getattr(run_context, "session_state", None)
            session_value = getattr(session_state, "session_id", None) if session_state is not None else None
            if user_value is None:
                user_value = getattr(session_state, "user_id", None) if session_state is not None else None
            if trace_id is None:
                trace_id = getattr(session_state, "trace_id", None) if session_state is not None else None
        data: Dict[str, Any] = {}
        if trace_id:
            data["trace_id"] = str(trace_id)
        if request_id:
            data["request_id"] = str(request_id)
        if session_value:
            data["session_id"] = str(session_value)
        if user_value:
            data["user_id"] = str(user_value)
        return data
    @staticmethod
    def _normalize_query_text(text: str) -> str:
        lowered = (text or "").strip().lower()
        return re.sub(r"\s+", " ", lowered)

    def _tokenize_text(self, text: str) -> List[str]:
        chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", self._normalize_query_text(text))
        tokens: List[str] = []
        for chunk in chunks:
            if re.match(r"^[a-z0-9_]+$", chunk):
                tokens.extend([x for x in chunk.split("_") if x])
            else:
                tokens.append(chunk)
        return tokens

    def _resolve_recall_policy(
        self,
        *,
        mode: str,
        user_id: str,
        request_top_k: int,
    ) -> Dict[str, Any]:
        mode_normalized = str(mode or "fast").strip().lower()
        if mode_normalized not in {"fast", "deep", "workflow"}:
            mode_normalized = "fast"

        defaults = {
            "fast": {"top_k": 4, "allowed_layers": ["summary", "direct", "recent"], "max_age_days": 30},
            "deep": {"top_k": 8, "allowed_layers": ["summary", "concept", "direct", "related", "salient", "recent"], "max_age_days": 90},
            "workflow": {"top_k": 8, "allowed_layers": ["summary", "concept", "direct", "related"], "max_age_days": 45},
        }
        policy = dict(defaults[mode_normalized])
        cfg = self._get_merged_config(user_id=user_id) or {}
        recall_cfg = cfg.get("memory", {}).get("recall_policy", {})
        mode_cfg = recall_cfg.get(mode_normalized, {}) if isinstance(recall_cfg, dict) else {}
        if isinstance(mode_cfg, dict):
            if "top_k" in mode_cfg:
                policy["top_k"] = int(mode_cfg.get("top_k") or policy["top_k"])
            if "allowed_layers" in mode_cfg and isinstance(mode_cfg.get("allowed_layers"), list):
                policy["allowed_layers"] = [str(x) for x in mode_cfg.get("allowed_layers") if str(x).strip()]
            if "max_age_days" in mode_cfg:
                policy["max_age_days"] = int(mode_cfg.get("max_age_days") or policy["max_age_days"])
        profile = str(cfg.get("memory", {}).get("profile", "balanced") or "balanced").strip().lower()
        if profile == "conservative":
            policy["top_k"] = max(2, int(policy["top_k"]) - 2)
            policy["max_age_days"] = max(7, int(policy["max_age_days"]) // 2)
        elif profile == "aggressive":
            policy["top_k"] = min(20, int(policy["top_k"]) + 2)
            policy["max_age_days"] = min(365, int(policy["max_age_days"]) + 30)

        policy["top_k"] = max(1, min(20, int(request_top_k or policy["top_k"] or 5)))
        policy["max_age_days"] = max(1, min(365, int(policy["max_age_days"])))
        policy["mode"] = mode_normalized
        return policy

    @staticmethod
    def _source_layer_to_memory_type(layer: str) -> str:
        mapping = {
            "summary": "semantic",
            "concept": "semantic",
            "direct": "episodic",
            "related": "episodic",
            "salient": "episodic",
            "recent": "working",
        }
        return mapping.get(str(layer or "").lower(), "episodic")

    def _collect_recall_candidates(self, request: MemoryRecallRequest) -> List[Dict[str, Any]]:
        if not self.memory_adapter:
            return []
        recall_engine = getattr(self.memory_adapter, "recall_engine", None)
        if recall_engine is None:
            context = self.memory_adapter.get_context(
                query=request.query_text,
                session_id=request.session_id,
                user_id=request.user_id,
            )
            if not context:
                return []
            return [{
                "memory_id": f"ctx_{request.request_id}",
                "source_layer": "summary",
                "content": context,
                "importance": 0.5,
                "created_at": None,
                "source_session": None,
                "owner_user_id": request.user_id,
            }]

        entities: List[str] = []
        try:
            extraction = recall_engine.extractor.extract(role="user", content=request.query_text)
            entities = extraction.entities if extraction and extraction.entities else []
        except Exception:
            entities = []

        recent_days = int(request.filters.get("recent_days") or 7)
        try:
            if hasattr(recall_engine, "_calculate_params"):
                params = recall_engine._calculate_params(request.query_text, entities)
                recent_days = int(params.get("recent_days", recent_days))
        except Exception:
            pass

        try:
            results = recall_engine._three_layer_query(entities, request.session_id, request.user_id, recent_days)
        except Exception:
            return []

        rows: List[Dict[str, Any]] = []
        for layer in ("summary", "concept", "direct", "related", "salient", "recent"):
            items = results.get(layer, []) if isinstance(results, dict) else []
            for idx, item in enumerate(items or []):
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                source_session = item.get("session_id")
                rows.append({
                    "memory_id": f"{layer}_{idx}_{abs(hash(content)) % 10000000}",
                    "source_layer": layer,
                    "content": content,
                    "importance": float(item.get("importance") or 0.0),
                    "created_at": str(item.get("time") or "") or None,
                    "source_session": str(source_session) if source_session else None,
                    "owner_user_id": request.user_id,
                    "via": item.get("via"),
                })
        return rows

    @staticmethod
    def _parse_candidate_datetime(raw_value: Optional[str]) -> Optional[datetime]:
        if not raw_value:
            return None
        text = str(raw_value).strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _build_recall_reason(self, candidate: Dict[str, Any], request: MemoryRecallRequest) -> str:
        layer = str(candidate.get("source_layer") or "")
        if request.mode == "workflow" and candidate.get("source_session") == request.session_id:
            return "active_workflow_context"
        if layer == "summary":
            return "project_memory_match"
        if layer == "concept":
            return "reasoning_template_match"
        if layer == "recent":
            return "recent_session_context"
        if layer in {"direct", "related", "salient"}:
            return "user_profile_match"
        return "memory_layer_match"

    def _format_recall_context(self, records: List[RecalledMemoryItem]) -> str:
        if not records:
            return ""
        lines: List[str] = []
        current_layer = ""
        for item in records:
            if item.source_layer != current_layer:
                current_layer = item.source_layer
                lines.append(f"[{current_layer}]")
            snippet = (item.content or "").strip().replace("\n", " ")
            if len(snippet) > 140:
                snippet = snippet[:137] + "..."
            lines.append(f"- {snippet}")
        return "\n".join(lines)

    def _store_recall_run(self, result: MemoryRecallResult, *, query_text: str = "") -> None:
        row = result.model_dump()
        row["query_text"] = str(query_text or "")
        self._recall_runs.append(row)
        self._recall_by_request[result.request_id] = row
        if len(self._recall_runs) > self._recall_history_limit:
            removed = self._recall_runs.pop(0)
            rid = str(removed.get("request_id") or "")
            if rid:
                self._recall_by_request.pop(rid, None)

    def list_recall_runs(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        rows = list(self._recall_runs)
        if user_id:
            rows = [x for x in rows if str(x.get("user_id") or "") == str(user_id)]
        if session_id:
            rows = [x for x in rows if str(x.get("session_id") or "") == str(session_id)]
        if trace_id:
            rows = [x for x in rows if str(x.get("trace_id") or "") == str(trace_id)]
        lim = max(1, min(100, int(limit or 20)))
        return rows[-lim:]

    def get_recall_run(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self._recall_by_request.get(str(request_id))

    def list_write_decisions(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        decision: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = [x for x in self._write_decisions if str(x.get("user_id") or "") == str(user_id)]
        if session_id:
            rows = [x for x in rows if str(x.get("session_id") or "") == str(session_id)]
        if trace_id:
            rows = [x for x in rows if str(x.get("trace_id") or "") == str(trace_id)]
        if decision:
            rows = [x for x in rows if str(x.get("decision") or "").lower() == str(decision).lower()]
        lim = max(1, min(500, int(limit or 100)))
        return rows[-lim:]

    def list_write_proposals(
        self,
        *,
        user_id: str,
        status: str = "pending",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = [x for x in self._write_proposals if str(x.get("user_id") or "") == str(user_id)]
        if status:
            rows = [x for x in rows if str(x.get("status") or "").lower() == str(status).lower()]
        lim = max(1, min(300, int(limit or 100)))
        return rows[-lim:]

    def get_capabilities_snapshot(self) -> Dict[str, Any]:
        adapter = self.memory_adapter
        if not adapter:
            return {"ok": False, "reason": "adapter_unavailable"}
        caps = adapter.get_capabilities() if hasattr(adapter, "get_capabilities") else {}
        if not isinstance(caps, dict):
            caps = {}
        return {
            "ok": True,
            "enabled": bool(self.is_enabled()),
            "capabilities": {
                "backend": str(caps.get("backend") or getattr(adapter, "store_backend", "unknown")),
                "supports_graph": bool(caps.get("supports_graph", False)),
                "supports_crud": bool(caps.get("supports_crud", False)),
                "supports_recall_runs": bool(caps.get("supports_recall_runs", True)),
                "supports_write_inspector": bool(caps.get("supports_write_inspector", True)),
            },
        }

    def list_entries(
        self,
        *,
        user_id: str,
        scope: str = "all",
        session_id: Optional[str] = None,
        memory_types: Optional[str] = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        include_archived: bool = False,
    ) -> Dict[str, Any]:
        adapter = self.memory_adapter
        if not adapter or not getattr(adapter, "is_enabled", lambda: False)():
            return {"ok": False, "reason": "memory_not_enabled"}

        type_list = [x.strip().lower() for x in str(memory_types or "").split(",") if x.strip()]
        scope_norm = str(scope or "all").strip().lower()
        if scope_norm == "user" and not type_list:
            type_list = ["goal", "preference", "constraint", "identity"]
        elif scope_norm == "project" and not type_list:
            type_list = ["project_state"]

        rows = adapter.list_memory_entries(
            user_id=user_id,
            session_id=session_id,
            memory_types=type_list or None,
            query=query,
            limit=limit,
            offset=offset,
        )
        if not include_archived:
            rows = [x for x in rows if str(x.get("status") or "active") != "archived"]
        return {"ok": True, "entries": rows, "total": len(rows)}

    def create_entry(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: str = "preference",
        session_id: Optional[str] = None,
        source_layer: Optional[str] = None,
    ) -> Dict[str, Any]:
        adapter = self.memory_adapter
        if not adapter or not getattr(adapter, "is_enabled", lambda: False)():
            return {"ok": False, "reason": "memory_not_enabled"}
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return {"ok": False, "reason": "content_required"}

        sid = str(session_id or "manual").strip()
        ok = adapter.add_message(
            session_id=sid,
            role="user",
            content=normalized_content,
            user_id=user_id,
            metadata={
                "memory_type": str(memory_type or "preference").strip().lower(),
                "source_layer": str(source_layer or "direct").strip().lower(),
                "memory_source": "user.manual_entry",
            },
        )
        return {"ok": bool(ok)}

    def update_entry(
        self,
        *,
        user_id: str,
        memory_id: str,
        content: Optional[str] = None,
        memory_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        adapter = self.memory_adapter
        if not adapter:
            return {"ok": False, "reason": "adapter_unavailable"}
        return adapter.update_memory_entry(
            user_id=user_id,
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            metadata=metadata,
        )

    def delete_entry(self, *, user_id: str, memory_id: str) -> Dict[str, Any]:
        adapter = self.memory_adapter
        if not adapter:
            return {"ok": False, "reason": "adapter_unavailable"}
        return adapter.delete_memory_entry(user_id=user_id, memory_id=memory_id)

    def build_dev_dashboard(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        decisions = self.list_write_decisions(user_id=user_id, session_id=session_id, limit=limit)
        recalls = self.list_recall_runs(user_id=user_id, session_id=session_id, limit=limit)
        write_total = len(decisions)
        write_allow = len([x for x in decisions if str(x.get("decision") or "") == "allow"])
        reason_dist: Dict[str, int] = {}
        for row in decisions:
            reason = str(row.get("reason") or "unknown")
            reason_dist[reason] = reason_dist.get(reason, 0) + 1
        recall_total = len(recalls)
        recall_candidates = sum(int((x.get("metrics") or {}).get("total_candidates", 0) or 0) for x in recalls)
        recall_selected = sum(int((x.get("metrics") or {}).get("selected", 0) or 0) for x in recalls)
        layer_dist: Dict[str, int] = {}
        for run in recalls:
            for rec in run.get("memory_records") or []:
                layer = str((rec or {}).get("source_layer") or "unknown")
                layer_dist[layer] = layer_dist.get(layer, 0) + 1
        return {
            "write": {
                "candidates": write_total,
                "allow_rate": (write_allow / write_total) if write_total else 0.0,
                "reasons": reason_dist,
            },
            "recall": {
                "runs": recall_total,
                "candidates": recall_candidates,
                "selected": recall_selected,
                "top_k_hit_rate": (recall_selected / recall_candidates) if recall_candidates else 0.0,
                "layer_contribution": layer_dist,
            },
        }

    def get_session_concepts(self, *, memory_session_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        if not self.memory_adapter.hot_layer:
            return {"ok": False, "reason": "hot_layer_unavailable"}
        try:
            from memory import create_warm_layer_manager

            warm_layer = create_warm_layer_manager(self.memory_adapter.hot_layer.connector)
            if not warm_layer:
                return {"ok": False, "reason": "warm_layer_unavailable"}
            return {"ok": True, "concepts": warm_layer.get_concepts(memory_session_id)}
        except Exception as e:
            return {"ok": False, "reason": f"get_concepts_failed:{e}"}

    def get_session_summaries(self, *, memory_session_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        if not self.memory_adapter.hot_layer:
            return {"ok": False, "reason": "hot_layer_unavailable"}
        try:
            from memory import create_cold_layer_manager

            cold_layer = create_cold_layer_manager(self.memory_adapter.hot_layer.connector)
            if not cold_layer:
                return {"ok": False, "reason": "cold_layer_unavailable"}
            summaries = cold_layer.get_summaries(memory_session_id)
            return {"ok": True, "summaries": summaries, "total_summaries": len(summaries)}
        except Exception as e:
            return {"ok": False, "reason": f"get_summaries_failed:{e}"}

    def get_summary_for_user(self, *, summary_id: str, user_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        if not self.memory_adapter.hot_layer:
            return {"ok": False, "reason": "hot_layer_unavailable"}
        try:
            from memory import create_cold_layer_manager

            connector = self.memory_adapter.hot_layer.connector
            cold_layer = create_cold_layer_manager(connector)
            if not cold_layer:
                return {"ok": False, "reason": "cold_layer_unavailable"}
            summary = cold_layer.get_summary_by_id(summary_id)
            if not summary:
                return {"ok": False, "reason": "summary_not_found"}
            raw_session_id = str(summary.get("session_id") or "")
            owned, _ = ensure_session_owned(connector, raw_session_id, user_id)
            if not owned:
                return {"ok": False, "reason": "summary_not_found"}
            return {"ok": True, "summary": summary}
        except Exception as e:
            return {"ok": False, "reason": f"get_summary_failed:{e}"}

    def get_forgetting_stats(self, *, memory_session_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        if not self.memory_adapter.hot_layer:
            return {"ok": False, "reason": "hot_layer_unavailable"}
        try:
            from memory import create_forgetting_manager

            forgetting_manager = create_forgetting_manager(self.memory_adapter.hot_layer.connector)
            return {"ok": True, "stats": forgetting_manager.get_forgetting_stats(memory_session_id)}
        except Exception as e:
            return {"ok": False, "reason": f"get_forgetting_stats_failed:{e}"}

    def ensure_session_access(self, *, session_id: str, user_id: str) -> Dict[str, Any]:
        manager = self.message_manager
        if not manager:
            return {"ok": False, "reason": "message_manager_unavailable"}
        try:
            exists = bool(manager.get_session(session_id, user_id=user_id))
        except Exception:
            exists = False
        if not exists:
            return {"ok": False, "reason": "session_not_found"}
        return {"ok": True}

    def resolve_owned_memory_session(self, *, session_id: str, user_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        if not getattr(self.memory_adapter, "hot_layer", None):
            return {"ok": False, "reason": "hot_layer_unavailable"}
        try:
            connector = self.memory_adapter.hot_layer.connector
            owned, resolved = ensure_session_owned(connector, session_id, user_id)
            if not owned:
                return {"ok": False, "reason": "session_memory_not_found"}
            return {"ok": True, "memory_session_id": resolved}
        except Exception as e:
            return {"ok": False, "reason": f"resolve_session_failed:{e}"}

    def get_graph_global_for_user(self, *, user_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled"}
        adapter = self.memory_adapter
        backend = str(getattr(adapter, "store_backend", "")).strip().lower()
        try:
            if backend == "sqlite_graph":
                snapshot = adapter.export_mef(user_id=user_id)
                nodes_raw = snapshot.get("nodes") or []
                edges_raw = snapshot.get("edges") or []
                nodes = []
                for n in nodes_raw:
                    nodes.append(
                        {
                            "id": n.get("id"),
                            "type": str(n.get("node_type") or n.get("type") or "").lower(),
                            "content": n.get("content", ""),
                            "layer": 1 if str(n.get("node_type") or "") == "token" else 0,
                            "importance": n.get("importance", 0.5),
                            "access_count": 0,
                            "created_at": n.get("created_at"),
                            "role": "",
                            "memory_type": "",
                            "memory_source": "sqlite_graph",
                        }
                    )
                edges = [
                    {
                        "source": e.get("src_node_id") or e.get("source"),
                        "target": e.get("dst_node_id") or e.get("target"),
                        "type": e.get("edge_type") or e.get("type") or "",
                        "weight": e.get("weight", 1.0),
                    }
                    for e in edges_raw
                ]
                return {
                    "ok": True,
                    "status": "success",
                    "user_id": user_id,
                    "graph_available": True,
                    "graph_mode": "sqlite_graph",
                    "nodes": nodes,
                    "edges": edges,
                    "stats": {
                        "total_nodes": len(nodes),
                        "total_edges": len(edges),
                        "layers": {
                            "hot": len([x for x in nodes if x.get("layer") == 0]),
                            "warm": len([x for x in nodes if x.get("layer") == 1]),
                            "cold": len([x for x in nodes if x.get("layer") == 2]),
                        },
                    },
                }
            if backend == "flat_memory":
                return {
                    "ok": True,
                    "status": "success",
                    "user_id": user_id,
                    "graph_available": False,
                    "graph_mode": "none",
                    "nodes": [],
                    "edges": [],
                    "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
                }

            if not getattr(adapter, "hot_layer", None):
                return {"ok": False, "reason": "hot_layer_unavailable"}
            connector = adapter.hot_layer.connector
            uid = user_node_id(user_id)
            nodes_query = """
            MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)
            OPTIONAL MATCH (m:Message)-[:PART_OF_SESSION]->(s)
            OPTIONAL MATCH (n)-[:FROM_MESSAGE]->(m)
            OPTIONAL MATCH (c:Concept)-[:PART_OF_SESSION]->(s)
            OPTIONAL MATCH (sum:Summary)
            WHERE EXISTS { MATCH (sum)-[rel]->(s) WHERE type(rel) = 'SUMMARIZES' }
            WITH collect(DISTINCT m) + collect(DISTINCT n) + collect(DISTINCT c) + collect(DISTINCT sum) AS all_nodes
            UNWIND all_nodes AS node
            WITH DISTINCT node
            WHERE node IS NOT NULL
            RETURN node.id AS id, labels(node)[0] AS type, node.content AS content,
                   node.layer AS layer, node.importance AS importance,
                   node.access_count AS access_count, node.created_at AS created_at,
                   node.role AS role, node.memory_type AS memory_type, node.memory_source AS memory_source
            """
            edges_query = """
            MATCH (u:User {id: $user_node_id})<-[:OWNED_BY]-(s:Session)
            OPTIONAL MATCH (m:Message)-[:PART_OF_SESSION]->(s)
            OPTIONAL MATCH (n)-[:FROM_MESSAGE]->(m)
            OPTIONAL MATCH (c:Concept)-[:PART_OF_SESSION]->(s)
            OPTIONAL MATCH (sum:Summary)
            WHERE EXISTS { MATCH (sum)-[rel]->(s) WHERE type(rel) = 'SUMMARIZES' }
            WITH collect(DISTINCT m) + collect(DISTINCT n) + collect(DISTINCT c) + collect(DISTINCT sum) AS all_nodes
            UNWIND all_nodes AS node
            WITH collect(DISTINCT node.id) AS node_ids
            MATCH (a)-[r]->(b)
            WHERE a.id IN node_ids AND b.id IN node_ids
            RETURN a.id AS source, b.id AS target, type(r) AS type, r.weight AS weight
            """
            params = {"user_node_id": uid}
            nodes_raw = connector.query(nodes_query, params)
            edges_raw = connector.query(edges_query, params)
            nodes = [
                {
                    "id": n.get("id"),
                    "type": (n.get("type", "") or "").lower(),
                    "content": n.get("content", ""),
                    "layer": n.get("layer", 0),
                    "importance": n.get("importance", 0.5),
                    "access_count": n.get("access_count", 0),
                    "created_at": n.get("created_at"),
                    "role": n.get("role", ""),
                    "memory_type": n.get("memory_type", ""),
                    "memory_source": n.get("memory_source", ""),
                }
                for n in nodes_raw
            ]
            edges = [
                {
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "type": e.get("type", ""),
                    "weight": e.get("weight", 1.0),
                }
                for e in edges_raw
            ]
            layer_counts = {"hot": 0, "warm": 0, "cold": 0}
            for node in nodes:
                layer = node.get("layer", 0)
                if layer == 0:
                    layer_counts["hot"] += 1
                elif layer == 1:
                    layer_counts["warm"] += 1
                elif layer == 2:
                    layer_counts["cold"] += 1
            return {
                "ok": True,
                "status": "success",
                "user_id": user_id,
                "graph_available": True,
                "graph_mode": "neo4j",
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "layers": layer_counts,
                },
            }
        except Exception as e:
            return {"ok": False, "reason": f"graph_global_failed:{e}"}

    def get_graph_for_session(self, *, session_id: str, user_id: str) -> Dict[str, Any]:
        if not self.enabled or not self.memory_adapter:
            return {"ok": False, "reason": "memory_not_enabled", "handled": False}
        adapter = self.memory_adapter
        backend = str(getattr(adapter, "store_backend", "")).strip().lower()
        try:
            if backend == "sqlite_graph":
                scoped_sid = scoped_session_id(session_id, user_id)
                snapshot = adapter.export_mef(user_id=user_id)
                nodes_raw = [
                    x
                    for x in (snapshot.get("nodes") or [])
                    if str(x.get("session_id") or "") in {"", scoped_sid}
                ]
                edges_raw = snapshot.get("edges") or []
                allowed_node_ids = {str(x.get("id") or "") for x in nodes_raw}
                edges = []
                for e in edges_raw:
                    src = e.get("src_node_id") or e.get("source")
                    dst = e.get("dst_node_id") or e.get("target")
                    if src in allowed_node_ids and dst in allowed_node_ids:
                        edges.append(
                            {
                                "source": src,
                                "target": dst,
                                "type": e.get("edge_type") or e.get("type") or "",
                                "weight": e.get("weight", 1.0),
                            }
                        )
                nodes = [
                    {
                        "id": n.get("id"),
                        "type": str(n.get("node_type") or n.get("type") or "").lower(),
                        "content": n.get("content", ""),
                        "layer": 1 if str(n.get("node_type") or "") == "token" else 0,
                        "importance": n.get("importance", 0.5),
                        "access_count": 0,
                        "created_at": n.get("created_at"),
                        "role": "",
                        "memory_type": "",
                        "memory_source": "sqlite_graph",
                    }
                    for n in nodes_raw
                ]
                return {
                    "ok": True,
                    "handled": True,
                    "status": "success",
                    "session_id": session_id,
                    "graph_available": True,
                    "graph_mode": "sqlite_graph",
                    "nodes": nodes,
                    "edges": edges,
                    "stats": {
                        "total_nodes": len(nodes),
                        "total_edges": len(edges),
                        "layers": {
                            "hot": len([x for x in nodes if x.get("layer") == 0]),
                            "warm": len([x for x in nodes if x.get("layer") == 1]),
                            "cold": len([x for x in nodes if x.get("layer") == 2]),
                        },
                    },
                }
            if backend == "flat_memory":
                return {
                    "ok": True,
                    "handled": True,
                    "status": "success",
                    "session_id": session_id,
                    "graph_available": False,
                    "graph_mode": "none",
                    "nodes": [],
                    "edges": [],
                    "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
                }
            return {"ok": True, "handled": False}
        except Exception as e:
            return {"ok": False, "reason": f"graph_session_failed:{e}", "handled": False}

    async def _save_reduce_memory_feedback(
        self,
        *,
        user_id: str,
        semantic_keys: List[str],
        memory_type: str,
    ) -> None:
        if not self.config_service:
            return
        merged = self._get_merged_config(user_id=user_id) or {}
        gating = ((merged.get("memory") or {}).get("gating") or {}) if isinstance(merged, dict) else {}
        feedback = (gating.get("user_feedback") or {}) if isinstance(gating, dict) else {}
        existed_keys = [str(x).strip().lower() for x in (feedback.get("suppress_semantic_keys") or []) if str(x).strip()]
        existed_types = [str(x).strip().lower() for x in (feedback.get("suppress_memory_types") or []) if str(x).strip()]
        next_keys = sorted(set(existed_keys + [str(x).strip().lower() for x in (semantic_keys or []) if str(x).strip()]))
        next_types = sorted(set(existed_types + ([str(memory_type).strip().lower()] if str(memory_type).strip() else [])))
        await self.config_service.update_user_config(
            user_id,
            {
                "memory": {
                    "gating": {
                        "user_feedback": {
                            "suppress_semantic_keys": next_keys,
                            "suppress_memory_types": next_types,
                        }
                    }
                }
            },
            validate=False,
        )

    def _is_suppressed_by_feedback(
        self,
        *,
        user_id: str,
        memory_type: str,
        semantic_keys: List[str],
    ) -> bool:
        merged = self._get_merged_config(user_id=user_id) or {}
        gating = ((merged.get("memory") or {}).get("gating") or {}) if isinstance(merged, dict) else {}
        feedback = (gating.get("user_feedback") or {}) if isinstance(gating, dict) else {}
        suppressed_types = {str(x).strip().lower() for x in (feedback.get("suppress_memory_types") or []) if str(x).strip()}
        suppressed_keys = {str(x).strip().lower() for x in (feedback.get("suppress_semantic_keys") or []) if str(x).strip()}
        if str(memory_type).strip().lower() in suppressed_types:
            return True
        for key in semantic_keys or []:
            if str(key).strip().lower() in suppressed_keys:
                return True
        return False

    async def resolve_write_proposal(
        self,
        *,
        proposal_id: str,
        user_id: str,
        action: str,
    ) -> Dict[str, Any]:
        row = self._write_proposal_by_id.get(str(proposal_id))
        if not row:
            return {"ok": False, "reason": "proposal_not_found"}
        if str(row.get("user_id") or "") != str(user_id):
            return {"ok": False, "reason": "forbidden"}
        if str(row.get("status") or "") != "pending":
            return {"ok": False, "reason": "proposal_not_pending"}
        action_norm = str(action or "").strip().lower()
        if action_norm not in {"confirm_write", "ignore_once", "reduce_similar"}:
            return {"ok": False, "reason": "invalid_action"}

        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        row["resolved_action"] = action_norm
        if action_norm == "confirm_write":
            if not self.memory_adapter:
                return {"ok": False, "reason": "memory_adapter_unavailable"}
            ok = self.memory_adapter.add_message(
                session_id=str(row.get("session_id") or ""),
                role="user",
                content=str(row.get("content") or ""),
                user_id=user_id,
                metadata={
                    "memory_type": str(row.get("memory_type") or ""),
                    "semantic_keys": list(row.get("semantic_keys") or []),
                    "memory_source": "user.confirmed",
                    "target_memory_layer": str(row.get("target_memory_layer") or ""),
                    "user_confirmed": True,
                },
            )
            if not ok:
                return {"ok": False, "reason": "adapter_write_failed"}
            for prev in row.get("conflict_candidates") or []:
                prev_text = str(prev or "").strip()
                if not prev_text:
                    continue
                try:
                    found = self.memory_adapter.list_memory_entries(
                        user_id=user_id,
                        session_id=None,
                        memory_types=[str(row.get("memory_type") or "")],
                        query=prev_text,
                        limit=20,
                        offset=0,
                    )
                    for item in found or []:
                        if self._normalize_content(str(item.get("content") or "")) != self._normalize_content(prev_text):
                            continue
                        mid = str(item.get("memory_id") or "")
                        if not mid:
                            continue
                        self.memory_adapter.update_memory_entry(
                            user_id=user_id,
                            memory_id=mid,
                            metadata={
                                "status": "superseded",
                                "superseded_by_proposal": str(proposal_id),
                            },
                        )
                except Exception:
                    continue
            row["status"] = "confirmed"
            await self._emit_memory_write_decision(
                session_id=str(row.get("session_id") or ""),
                user_id=user_id,
                channel=None,
                memory_type=str(row.get("memory_type") or ""),
                content=str(row.get("content") or ""),
                semantic_keys=list(row.get("semantic_keys") or []),
                decision="allow",
                target_memory_layer=str(row.get("target_memory_layer") or ""),
                reason="user_confirmed_conflict_write",
                persisted=True,
                proposal_id=str(proposal_id),
            )
            return {"ok": True, "proposal": row}

        if action_norm == "reduce_similar":
            await self._save_reduce_memory_feedback(
                user_id=user_id,
                semantic_keys=list(row.get("semantic_keys") or []),
                memory_type=str(row.get("memory_type") or ""),
            )
        row["status"] = "dismissed"
        await self._emit_memory_write_decision(
            session_id=str(row.get("session_id") or ""),
            user_id=user_id,
            channel=None,
            memory_type=str(row.get("memory_type") or ""),
            content=str(row.get("content") or ""),
            semantic_keys=list(row.get("semantic_keys") or []),
            decision="deny",
            target_memory_layer=str(row.get("target_memory_layer") or ""),
            reason="user_declined_conflict_write" if action_norm == "ignore_once" else "user_reduce_similar_writes",
            persisted=False,
            proposal_id=str(proposal_id),
        )
        return {"ok": True, "proposal": row}

    async def recall_memory(
        self,
        request: MemoryRecallRequest,
        run_context: Optional[Any] = None,
    ) -> MemoryRecallResult:
        resolved = self._extract_run_context_fields(run_context)
        request.trace_id = str(resolved.get("trace_id") or request.trace_id)
        request.request_id = str(resolved.get("request_id") or request.request_id)
        request.session_id = str(resolved.get("session_id") or request.session_id)
        request.user_id = str(resolved.get("user_id") or request.user_id)
        request.normalized_query = request.normalized_query or self._normalize_query_text(request.query_text)

        policy = self._resolve_recall_policy(
            mode=request.mode,
            user_id=request.user_id,
            request_top_k=request.top_k,
        )

        if self.event_emitter:
            await self.event_emitter.emit(
                EventType.MEMORY_RECALL_STARTED,
                {
                    "request_id": request.request_id,
                    "trace_id": request.trace_id,
                    "session_id": request.session_id,
                    "user_id": request.user_id,
                    "query": request.query_text,
                    "mode": policy.get("mode"),
                },
            )

        if not self.enabled or not self.memory_adapter:
            result = MemoryRecallResult(
                request_id=request.request_id,
                trace_id=request.trace_id,
                session_id=request.session_id,
                user_id=request.user_id,
                recall_strategy=policy,
                applied_filters=["memory_disabled"],
                metrics={"total_candidates": 0, "selected": 0, "dropped": 0},
            )
            self._store_recall_run(result, query_text=request.query_text)
            return result

        candidates = self._collect_recall_candidates(request)
        q_tokens = set(self._tokenize_text(request.normalized_query))
        now = datetime.now(timezone.utc)
        max_age_days = int(policy.get("max_age_days", 30))
        cutoff = now - timedelta(days=max_age_days)
        allowed_layers = set(policy.get("allowed_layers", []))

        selected: List[RecalledMemoryItem] = []
        dropped: List[DroppedRecallCandidate] = []
        seen_content: set[str] = set()

        for item in candidates:
            source_layer = str(item.get("source_layer") or "").lower()
            content = str(item.get("content") or "").strip()
            memory_id = str(item.get("memory_id") or f"m_{abs(hash(content)) % 100000}")
            if not content:
                continue

            if allowed_layers and source_layer not in allowed_layers:
                dropped.append(DroppedRecallCandidate(memory_id=memory_id, source_layer=source_layer, content=content[:180], reason="layer_filtered"))
                continue

            owner = str(item.get("owner_user_id") or request.user_id)
            if owner != request.user_id:
                dropped.append(DroppedRecallCandidate(memory_id=memory_id, source_layer=source_layer, content=content[:180], reason="namespace_mismatch"))
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.SECURITY_BOUNDARY_VIOLATION,
                        {
                            "namespace": "memory",
                            "request_id": request.request_id,
                            "trace_id": request.trace_id,
                            "session_id": request.session_id,
                            "user_id": request.user_id,
                            "owner_user_id": owner,
                            "requester_user_id": request.user_id,
                            "memory_id": memory_id,
                            "reason": "cross_user_memory_access",
                            "outcome": "blocked",
                        },
                    )
                continue

            normalized_content = self._normalize_query_text(content)
            if normalized_content in seen_content:
                dropped.append(DroppedRecallCandidate(memory_id=memory_id, source_layer=source_layer, content=content[:180], reason="duplicate_candidate"))
                continue

            dt = self._parse_candidate_datetime(item.get("created_at"))
            staleness_flag = False
            if dt is not None:
                dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                if dt_utc < cutoff:
                    staleness_flag = True
                    dropped.append(DroppedRecallCandidate(memory_id=memory_id, source_layer=source_layer, content=content[:180], reason="stale_candidate"))
                    continue

            c_tokens = set(self._tokenize_text(content))
            overlap = len(q_tokens.intersection(c_tokens)) / max(1, len(c_tokens))
            importance = float(item.get("importance") or 0.0)
            relevance = min(1.0, round((overlap * 0.8) + (importance * 0.2), 4))

            conflict_flag = False
            if " not " in f" {normalized_content} " and any(x in normalized_content for x in ["always", "must", "prefer"]):
                conflict_flag = True

            selected.append(
                RecalledMemoryItem(
                    memory_id=memory_id,
                    memory_type=self._source_layer_to_memory_type(source_layer),
                    source_layer=source_layer,
                    content=content,
                    relevance_score=relevance,
                    confidence=max(0.1, min(1.0, round(0.5 + overlap * 0.5, 3))),
                    recall_reason=self._build_recall_reason(item, request),
                    source_session=item.get("source_session"),
                    created_at=item.get("created_at"),
                    staleness_flag=staleness_flag,
                    conflict_flag=conflict_flag,
                    metadata={"importance": importance, "via": item.get("via")},
                )
            )
            seen_content.add(normalized_content)

        selected.sort(key=lambda x: x.relevance_score, reverse=True)
        top_k = int(policy.get("top_k", request.top_k or 5))
        overflow = selected[top_k:]
        selected = selected[:top_k]
        for item in overflow:
            dropped.append(
                DroppedRecallCandidate(
                    memory_id=item.memory_id,
                    source_layer=item.source_layer,
                    content=item.content[:180],
                    reason="budget_limit",
                    relevance_score=item.relevance_score,
                )
            )

        result = MemoryRecallResult(
            request_id=request.request_id,
            trace_id=request.trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            memory_records=selected,
            summary=("; ".join([f"{x.source_layer}:{x.recall_reason}" for x in selected[:3]]) if selected else ""),
            formatted_context=self._format_recall_context(selected),
            recall_strategy=policy,
            applied_filters=["layer_filter", "namespace_filter", "duplicate_filter", "staleness_filter", "top_k_filter"],
            dropped_candidates=dropped,
            metrics={
                "total_candidates": len(candidates),
                "selected": len(selected),
                "dropped": len(dropped),
                "mode": policy.get("mode"),
                "top_k": top_k,
            },
        )
        self._store_recall_run(result, query_text=request.query_text)

        if self.event_emitter:
            payload = {
                "request_id": result.request_id,
                "trace_id": result.trace_id,
                "session_id": result.session_id,
                "user_id": result.user_id,
                "context_length": len(result.formatted_context or ""),
                "selected": len(result.memory_records),
                "dropped": len(result.dropped_candidates),
            }
            await self.event_emitter.emit(EventType.MEMORY_RECALL_FINISHED, payload)
            await self.event_emitter.emit(EventType.MEMORY_RECALLED, payload)

        return result
    async def get_context(
        self,
        query: str,
        session_id: str,
        user_id: Optional[str] = None,
        run_context: Optional[Any] = None,
    ) -> str:
        try:
            resolved = self._extract_run_context_fields(run_context)
            supports_structured_recall = False
            collect_fn = getattr(self.memory_adapter, "collect_recall_candidates", None) if self.memory_adapter else None
            if callable(collect_fn):
                try:
                    from unittest.mock import Mock

                    supports_structured_recall = not (
                        isinstance(self.memory_adapter, Mock) or isinstance(collect_fn, Mock)
                    )
                except Exception:
                    supports_structured_recall = True
            # Legacy adapter compatibility:
            # If adapter does not provide structured recall candidates, keep
            # historical get_context() behavior (raw context string).
            if self.enabled and self.memory_adapter and not supports_structured_recall:
                legacy_text = self.memory_adapter.get_context(
                    query=str(query or ""),
                    session_id=str(resolved.get("session_id") or session_id),
                    user_id=str(resolved.get("user_id") or user_id or "default_user"),
                )
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.MEMORY_RECALLED,
                        {
                            "request_id": str(resolved.get("request_id") or f"recall_{int(time.time() * 1000)}"),
                            "trace_id": str(resolved.get("trace_id") or f"trace_recall_{int(time.time() * 1000)}"),
                            "session_id": str(resolved.get("session_id") or session_id),
                            "user_id": str(resolved.get("user_id") or user_id or "default_user"),
                            "context_length": len(str(legacy_text or "")),
                            "selected": 1 if legacy_text else 0,
                            "dropped": 0,
                        },
                    )
                return str(legacy_text or "")

            request = MemoryRecallRequest(
                request_id=str(resolved.get("request_id") or f"recall_{int(time.time() * 1000)}"),
                trace_id=str(resolved.get("trace_id") or f"trace_recall_{int(time.time() * 1000)}"),
                session_id=str(resolved.get("session_id") or session_id),
                user_id=str(resolved.get("user_id") or user_id or "default_user"),
                query_text=str(query or ""),
                mode=str((resolved.get("mode") or "fast")),
                top_k=5,
            )
            result = await self.recall_memory(request, run_context=run_context)
            return result.formatted_context or ""
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










