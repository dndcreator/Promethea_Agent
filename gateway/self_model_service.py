"""Personal working cognition and bounded projections of Runtime-owned facts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .cognitive_reducer import CognitiveRecallPolicy, CognitiveReducer
from .protocol import EventType
from .self_model_state import SelfModelStateStore
from .semantic_ui import SemanticUI


SELF_MODEL_DOCS = [
    "docs/runtime-overview.md",
    "docs/architecture/runtime-io.md",
    "docs/architecture/tool-runtime.md",
    "docs/architecture/memory-model.md",
    "docs/architecture/conversation-pipeline.md",
    "docs/ui-overview.md",
]


class SelfModelService:
    """Projects runtime-owned state into a bounded model of self and cognition.

    This service owns the projection, not the underlying memory, task, tool, or
    reasoning state. Passive projection is deterministic; explicit cognition
    recall may use a bounded LLM reducer and never writes memory directly.
    """

    def __init__(
        self,
        *,
        memory_service: Optional[Any] = None,
        task_service: Optional[Any] = None,
        capability_service: Optional[Any] = None,
        config_service: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        workspace_root: Optional[str] = None,
        message_manager: Optional[Any] = None,
        workflow_engine: Optional[Any] = None,
    ) -> None:
        self.memory_service = memory_service
        self.task_service = task_service
        self.capability_service = capability_service
        self.config_service = config_service
        self.event_emitter = event_emitter
        self.llm_client = llm_client
        self.message_manager = message_manager
        self.workflow_engine = workflow_engine
        self.agent_messages = None
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.self_model_path = self.workspace_root / "memory" / "self_model.json"
        self.state = SelfModelStateStore(self.workspace_root / ".runtime" / "self-model" / "state.json")
        from config import config
        from .environment_sources import EnvironmentSources
        from .environment_context import EnvironmentViews
        self.environment_sources = EnvironmentSources(message_manager=message_manager, task_service=task_service, capability_service=capability_service)
        self.environment = EnvironmentViews(resolver=self.environment_sources.inspect, ttl_seconds=config.self_model.environment_ttl_s)
        self.semantic_ui = SemanticUI(store=self.state, message_manager=message_manager, event_emitter=event_emitter, environment=self.environment)
        if event_emitter is not None:
            for event in (EventType.INTERACTION_COMPLETED, EventType.MEMORY_REPLAY_COMPLETED, EventType.MEMORY_SAVED, EventType.MEMORY_UPDATE,
                          EventType.GOAL_GAPS_UPDATED, EventType.TASK_EXECUTION_SETTLED,
                          EventType.ACTION_OBSERVATION_COMMITTED, EventType.ENVIRONMENT_STATE_CHANGED,
                          EventType.SEMANTIC_UI_INTERACTED, EventType.UI_CONTEXT_CHANGED):
                event_emitter.on(event, self.observe)

    def observe(self, event):
        user = event.payload.get("user_id")
        if not user or (event.seq and event.seq <= self.state.get(user).last_event_seq):
            return
        def change(current):
            current.last_event_seq = max(current.last_event_seq, event.seq or 0)
            current.changes = [*current.changes, {
                "event_id": event.event_id, "seq": event.seq, "event_type": event.event.value,
                **{key: event.payload[key] for key in ("task_id", "session_id", "expression_id") if event.payload.get(key)},
            }][-24:]
        self.state.update(user, change)

    async def update_situation(self, user, command):
        def apply(current):
            current.attention = command.attention
            current.questions = command.questions
            current.interpretation = command.interpretation
            current.cognition_revision += 1
        current = self.state.update(user, apply, expected_revision=command.expected_revision)
        if self.event_emitter is not None:
            await self.event_emitter.emit(EventType.SELF_MODEL_UPDATED, {"user_id": user, "revision": current.revision})
        return {"ok": True, "revision": current.cognition_revision, "classification": "working_interpretation_not_memory_fact"}

    def working_context(self, user):
        current = self.state.get(user)
        if user not in self.state.users:
            return {"revision": 0, "attention": [], "questions": [], "interpretation": "", "surface": self.environment.current_surface(user)}
        result = current.model_dump(exclude={"expressions", "cognition_revision"})
        result["state_revision"], result["revision"] = current.revision, current.cognition_revision
        result["surface"] = self.environment.current_surface(user)
        log = getattr(self.event_emitter, "event_log", None)
        if log is not None:
            for change in result["changes"][-4:]:
                seq = change.get("seq") or 0
                rows = log.query(user_id=user, after_seq=seq - 1, limit=1, oldest_first=True) if seq else []
                if rows and rows[0]["seq"] == seq:
                    change["observation_excerpt"] = json.dumps(rows[0]["payload"], ensure_ascii=False, default=str)[:1200]
        return result

    async def build_observation_context(self, user):
        from config import config
        environment = await self.environment.snapshot(user)
        return {"environment": environment, "observation_prompt": self.environment.prompt(environment, config.self_model.observation_chars)}

    def _resolve_workspace_path(self, path_str: str) -> Path:
        path = (self.workspace_root / path_str).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError(f"Path outside workspace is not allowed: {path}") from exc
        return path

    @staticmethod
    def _doc_outline(text: str, *, max_lines: int = 80) -> List[str]:
        lines: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if line and (line.startswith("#") or line.startswith("- ")):
                lines.append(line)
            if len(lines) >= max_lines:
                break
        return lines

    def _read_docs(self, *, max_chars_per_file: int) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        cap = max(500, int(max_chars_per_file))
        for relative_path in SELF_MODEL_DOCS:
            path = self._resolve_workspace_path(relative_path)
            if not path.is_file():
                docs.append({"path": relative_path, "exists": False, "sha256": "", "outline": []})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                {
                    "path": relative_path,
                    "exists": True,
                    "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                    "outline": self._doc_outline(text[:cap]),
                }
            )
        return docs

    @staticmethod
    def _capability_inventory() -> Dict[str, Any]:
        return {
            "conversation_runtime": {
                "modules": ["ConversationService", "RunContext", "PromptAssembler"],
                "role": "compile one model turn from runtime-owned context",
            },
            "memory": {
                "modules": ["MemoryService", "memory recall", "memory write gate", "hippocampus"],
                "role": "own recall, durable writes, and asynchronous consolidation",
            },
            "reasoning": {
                "modules": ["main model control loop", "ReasoningService", "reasoning tree"],
                "role": "own explicit multi-step reasoning and its observable summaries",
            },
            "tools": {
                "modules": ["CapabilityService", "ToolRegistry", "ToolPolicy"],
                "role": "own discovery, policy, execution, and observations",
            },
            "tasks_and_workflows": {
                "modules": ["TaskService", "TaskRuntime", "WorkflowEngine"],
                "role": "own durable task and workflow execution state",
            },
            "self_model": {
                "modules": ["SelfModelService"],
                "role": "project owned state into bounded self-knowledge and cognition",
            },
            "initiative": {
                "modules": ["AmbientService", "AgentMessages"],
                "role": "schedule proactive participation and coordinate delivery; cognition belongs to SelfModelService",
            },
            "self_evolve": {
                "modules": ["SelfEvolveService"],
                "role": "consume the self model for append-only capability evolution and validation",
            },
        }

    @classmethod
    def _summary(cls, docs: List[Dict[str, Any]]) -> str:
        available = [str(doc.get("path")) for doc in docs if doc.get("exists")]
        return "\n".join(
            [
                "Promethea self model, derived from repository architecture documents.",
                "Service ownership:",
                "- ConversationService composes model turns through RunContext and PromptAssembler.",
                "- MemoryService owns memory; SelfModelService only projects cognition from it.",
                "- ReasoningService, CapabilityService, TaskService, and WorkflowEngine retain their own state.",
                "- SelfEvolveService consumes this model for controlled code evolution.",
                "- Claims about live tools, files, or runtime state still require current observations.",
                f"Source docs: {', '.join(available) if available else 'none'}",
            ]
        )

    def freshness(self, model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if model is None:
            if not self.self_model_path.exists():
                return {"exists": False, "stale": True, "changed_sources": [], "missing_sources": SELF_MODEL_DOCS}
            try:
                model = json.loads(self.self_model_path.read_text(encoding="utf-8"))
            except Exception:
                return {"exists": True, "stale": True, "changed_sources": ["memory/self_model.json"], "missing_sources": []}
        previous = {
            str(row.get("path")): row
            for row in (model.get("documents") or [])
            if isinstance(row, dict)
        }
        changed: List[str] = []
        missing: List[str] = []
        for doc in self._read_docs(max_chars_per_file=500):
            path = str(doc.get("path") or "")
            if not doc.get("exists"):
                missing.append(path)
            elif (previous.get(path) or {}).get("sha256") != doc.get("sha256"):
                changed.append(path)
        return {"exists": True, "stale": bool(changed or missing), "changed_sources": changed, "missing_sources": missing}

    async def build_self_model(self, max_chars_per_file: int = 5000) -> Dict[str, Any]:
        docs = self._read_docs(max_chars_per_file=max_chars_per_file)
        summary = self._summary(docs)
        model = {
            "kind": "promethea_self_model",
            "version": 3,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "self_model.docs",
            "summary": summary,
            "architecture_map": {
                "context_flow": "runtime services -> SelfModelService projection -> RunContext -> PromptAssembler",
                "feedback_flow": "runtime events -> MemoryService/Hippocampus -> later cognition projection",
                "ownership": {name: value["role"] for name, value in self._capability_inventory().items()},
            },
            "capability_inventory": self._capability_inventory(),
            "runtime_boundaries": [
                "The self model is a projection and does not own memory, tasks, tools, reasoning, or workflows.",
                "Do not claim live inspection without a current runtime observation.",
                "Uncertain cognition is context for caution, not established fact.",
            ],
            "model_sections": {
                "self": {"source": "self_model.docs", "summary": summary},
                "cognition": {"source": "user_scoped_memory_projection", "persisted_in_self_model": False},
                "capabilities": {"source": "runtime_services_and_docs", "areas": sorted(self._capability_inventory())},
            },
            "documents": docs,
        }
        model["freshness"] = self.freshness(model)
        self.self_model_path.parent.mkdir(parents=True, exist_ok=True)
        self.self_model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "self_model": model, "path": self.self_model_path.relative_to(self.workspace_root).as_posix()}

    async def get_self_model(self) -> Dict[str, Any]:
        relative_path = self.self_model_path.relative_to(self.workspace_root).as_posix()
        if not self.self_model_path.exists():
            return {"ok": True, "exists": False, "self_model": None, "path": relative_path}
        model = json.loads(self.self_model_path.read_text(encoding="utf-8"))
        model["freshness"] = self.freshness(model)
        return {"ok": True, "exists": True, "self_model": model, "path": relative_path}

    def status_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {"exists": self.self_model_path.exists(), "path": str(self.self_model_path)}
        if not snapshot["exists"]:
            return snapshot
        try:
            model = json.loads(self.self_model_path.read_text(encoding="utf-8"))
            snapshot.update(
                generated_at=model.get("generated_at"),
                version=model.get("version"),
                freshness=self.freshness(model),
                capability_areas=sorted((model.get("capability_inventory") or {}).keys()),
            )
        except Exception:
            snapshot["error"] = "failed_to_read_self_model"
        return snapshot

    @staticmethod
    def _cognition_domain(memory_type: str, metadata: Dict[str, Any]) -> str:
        explicit = str(metadata.get("cognition_domain") or "").strip().lower()
        if explicit in {"self", "user", "projects", "world", "active"}:
            return explicit
        normalized = str(memory_type or "").strip().lower()
        if normalized in {"identity", "preference", "constraint", "relationship"}:
            return "user"
        if normalized in {"goal", "project_state", "task", "plan"}:
            return "projects"
        if normalized in {"capability", "self", "self_model"}:
            return "self"
        return "world"

    @staticmethod
    def _cognition_state(row: Dict[str, Any], metadata: Dict[str, Any]) -> str:
        explicit = str(metadata.get("cognition_state") or "").strip().lower()
        if explicit in {"current", "evolving", "uncertain", "historical"}:
            return explicit
        if str(row.get("status") or "active").strip().lower() in {"archived", "superseded", "historical"}:
            return "historical"
        modality = str(metadata.get("memory_modality") or metadata.get("modality") or "").strip().lower()
        persistence = str(metadata.get("memory_persistence") or metadata.get("persistence") or "").strip().lower()
        return "evolving" if modality in {"plan", "hypothetical"} or persistence in {"ephemeral", "bounded"} else "current"

    @staticmethod
    def _importance(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    def project_cognition(
        self,
        *,
        user_id: str,
        entries: List[Dict[str, Any]],
        proposals: Optional[List[Dict[str, Any]]] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for index, row in enumerate(entries or []):
            if not isinstance(row, dict):
                continue
            content = " ".join(str(row.get("content") or "").split()).strip()
            key = content.casefold()
            if not content or key in seen:
                continue
            seen.add(key)
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            memory_id = str(row.get("memory_id") or row.get("id") or f"memory-{index + 1}")
            kind = str(row.get("memory_type") or row.get("type") or "memory").strip().lower()
            semantic_keys = metadata.get("semantic_keys") if isinstance(metadata.get("semantic_keys"), list) else []
            items.append({
                "cognition_id": f"memory:{memory_id}", "content": content,
                "domain": self._cognition_domain(kind, metadata), "state": self._cognition_state(row, metadata),
                "kind": kind, "importance": self._importance(row.get("importance") or row.get("confidence"), 0.5),
                "relevance_score": self._importance(row.get("relevance_score"), 0.0),
                "updated_at": row.get("updated_at") or row.get("created_at"), "memory_id": memory_id,
                "source_layer": str(row.get("source_layer") or row.get("layer") or ""),
                "related": [str(value) for value in semantic_keys if str(value).strip()][:8], "action_required": False,
                "metadata": metadata,
            })
        for index, row in enumerate(proposals or []):
            if not isinstance(row, dict):
                continue
            content = " ".join(str(row.get("content") or "").split()).strip()
            if not content:
                continue
            proposal_id = str(row.get("proposal_id") or f"proposal-{index + 1}")
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            kind = str(row.get("memory_type") or "memory").strip().lower()
            items.append({
                "cognition_id": f"proposal:{proposal_id}", "content": content,
                "domain": self._cognition_domain(kind, metadata), "state": "uncertain", "kind": kind,
                "importance": self._importance(row.get("confidence"), 0.65),
                "updated_at": row.get("updated_at") or row.get("created_at"), "proposal_id": proposal_id,
                "source_layer": str(row.get("target_memory_layer") or ""),
                "related": [str(value) for value in row.get("semantic_keys") or [] if str(value).strip()][:8],
                "action_required": True,
            })
        rank = {"uncertain": 0, "current": 1, "evolving": 2, "historical": 3}
        items.sort(key=lambda item: (rank.get(str(item.get("state")), 9), -float(item.get("importance") or 0), str(item.get("updated_at") or "")))
        items = items[: max(1, min(500, int(limit)))]
        return {
            "version": "self_model.cognition.v1", "model_scope": "self_model.cognition",
            "user_id": str(user_id), "generated_at": datetime.now(timezone.utc).isoformat(), "items": items,
            "stats": {
                "total": len(items),
                "states": {state: sum(item.get("state") == state for item in items) for state in rank},
                "domains": {domain: sum(item.get("domain") == domain for item in items) for domain in ("self", "user", "projects", "world", "active")},
            },
        }

    def build_cognition_bundle(self, *, user_id: str, limit: int = 200) -> Dict[str, Any]:
        if self.memory_service is None:
            return {"ok": False, "reason": "memory_service_unavailable"}
        entries_result = self.memory_service.list_entries(user_id=user_id, scope="all", limit=limit, include_archived=True)
        if not entries_result.get("ok"):
            return {"ok": False, "reason": str(entries_result.get("reason") or "memory_unavailable")}
        proposals = self.memory_service.list_write_proposals(user_id=user_id, status="pending", limit=limit)
        return {"ok": True, "cognition": self.project_cognition(user_id=user_id, entries=list(entries_result.get("entries") or []), proposals=list(proposals or []), limit=limit)}

    def _merged_config(self, user_id: str) -> Dict[str, Any]:
        if self.config_service is None:
            return {}
        try:
            config = self.config_service.get_merged_config(user_id)
            return dict(config or {}) if isinstance(config, dict) else {}
        except Exception:
            return {}

    def _candidate_pool(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        limit: int,
        run_context: Optional[Any],
    ) -> Dict[str, Any]:
        if self.memory_service is None:
            return {"ok": False, "reason": "memory_service_unavailable", "candidates": []}
        retrieve = getattr(self.memory_service, "retrieve_candidates", None)
        if not callable(retrieve):
            result = self.memory_service.list_entries(
                user_id=user_id,
                scope="all",
                session_id=None,
                query=query,
                limit=limit,
                include_archived=True,
            )
            return {
                "ok": bool(result.get("ok")),
                "reason": result.get("reason"),
                "candidates": list(result.get("entries") or []),
            }
        return retrieve(
            query=query,
            session_id=session_id,
            user_id=user_id,
            limit=limit,
            run_context=run_context,
        )

    def _passive_candidate_pool(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
    ) -> Dict[str, Any]:
        """Deterministic high-precision recall for passive self-model projection."""
        if self.memory_service is None:
            return {"ok": False, "reason": "memory_service_unavailable", "candidates": []}
        search = getattr(self.memory_service, "search_entries", None)
        if not callable(search):
            return {"ok": False, "reason": "deterministic_search_unavailable", "candidates": []}
        result = search(user_id=user_id, query=query, limit=limit)
        if not isinstance(result, dict) or not result.get("ok"):
            return {
                "ok": False,
                "reason": str((result or {}).get("reason") or "deterministic_search_failed"),
                "candidates": [],
            }
        return {
            "ok": True,
            "query": query,
            "user_id": user_id,
            "candidates": list(result.get("entries") or []),
            "total": int(result.get("total") or 0),
            "retrieval_mode": "passive_deterministic",
        }

    async def _call_cognitive_llm(
        self,
        *,
        user_id: str,
        user_config: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        if self.llm_client is None or not hasattr(self.llm_client, "call_llm"):
            return {"status": "error", "content": ""}
        llm_config = user_config
        try:
            from gateway.user_secrets import resolve_memory_runtime_settings

            runtime = resolve_memory_runtime_settings(user_id, behavior_config=user_config)
            if runtime.get("model"):
                llm_config = {**user_config, "api": {**dict(user_config.get("api") or {}), **runtime}}
        except Exception:
            pass
        return await self.llm_client.call_llm(messages, user_config=llm_config, user_id=user_id)

    @staticmethod
    def _correlation(run_context: Optional[Any]) -> Dict[str, Any]:
        if run_context is None:
            return {}
        return {
            key: str(value)
            for key in ("request_id", "trace_id", "task_id", "run_id", "session_id")
            if (value := getattr(run_context, key, None))
        }

    async def recall_cognition(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        run_context: Optional[Any] = None,
        facets: Optional[List[str]] = None,
        mode: str = "auto",
        deadline_ms: Optional[int] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build one ephemeral, query-conditioned CognitionSnapshot."""
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"ok": False, "reason": "query_required"}
        config = dict(user_config or self._merged_config(user_id))
        policy = CognitiveRecallPolicy.from_config(config)
        correlation = self._correlation(run_context)
        event_payload = {
            "user_id": user_id,
            "session_id": session_id,
            "query": normalized_query,
            "requested_mode": str(mode or "auto"),
            **correlation,
        }
        if self.event_emitter:
            await self.event_emitter.emit(EventType.COGNITION_RECALL_STARTED, event_payload)
        try:
            pool = await asyncio.to_thread(
                self._candidate_pool,
                user_id=user_id,
                session_id=session_id,
                query=normalized_query,
                limit=policy.candidate_pool_limit,
                run_context=run_context,
            )
            if not pool.get("ok"):
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.COGNITION_RECALL_FAILED,
                        {**event_payload, "error": str(pool.get("reason") or "candidate_pool_unavailable")},
                    )
                return {"ok": False, "reason": str(pool.get("reason") or "candidate_pool_unavailable")}
            proposals = self.memory_service.list_write_proposals(
                user_id=user_id,
                status="pending",
                limit=policy.candidate_pool_limit,
            ) if self.memory_service is not None else []
            cognition = self.project_cognition(
                user_id=user_id,
                entries=list(pool.get("candidates") or []),
                proposals=list(proposals or []),
                limit=policy.candidate_pool_limit,
            )
            task_id = str(correlation.get("task_id") or "")
            if task_id and self.task_service is not None:
                try:
                    task = self.task_service.get_task(task_id, user_id=user_id)
                except Exception:
                    task = None
                if isinstance(task, dict):
                    task_content = " - ".join(
                        value
                        for value in (
                            str(task.get("title") or "").strip(),
                            str(task.get("objective") or "").strip(),
                            str(task.get("status") or "").strip(),
                        )
                        if value
                    )
                    if task_content:
                        cognition.setdefault("items", []).insert(
                            0,
                            {
                                "cognition_id": f"task:{task_id}",
                                "content": task_content,
                                "domain": "active",
                                "state": "evolving",
                                "kind": "task",
                                "importance": 1.0,
                                "relevance_score": 1.0,
                                "updated_at": task.get("updated_at"),
                                "related": [task_id],
                                "action_required": False,
                                "metadata": {"revision": task.get("revision")},
                            },
                        )
            reducer = CognitiveReducer(
                llm_call=lambda messages: self._call_cognitive_llm(
                    user_id=user_id,
                    user_config=config,
                    messages=messages,
                )
            )
            snapshot = await reducer.reduce(
                query=normalized_query,
                items=list(cognition.get("items") or []),
                policy=policy,
                facets=list(facets or []),
                requested_mode=mode,
                deadline_ms=deadline_ms,
            )
            snapshot["user_id"] = user_id
            snapshot["session_id"] = session_id
            snapshot["generated_at"] = datetime.now(timezone.utc).isoformat()
            snapshot["active"] = correlation
            if run_context is not None:
                try:
                    setattr(run_context, "cognition_snapshot", dict(snapshot))
                except Exception:
                    pass
            if self.memory_service is not None:
                try:
                    await self.memory_service.offer_cognition_snapshot(
                        user_id=user_id,
                        snapshot=snapshot,
                    )
                except Exception as exc:
                    logger.debug("SelfModelService: cognition hint handoff skipped: {}", exc)
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.COGNITION_RECALL_FINISHED,
                    {
                        **event_payload,
                        "mode": snapshot.get("mode"),
                        "candidate_count": (snapshot.get("metrics") or {}).get("candidate_count", 0),
                        "skip_count": (snapshot.get("metrics") or {}).get("skip_count", 0),
                        "duration_ms": (snapshot.get("metrics") or {}).get("duration_ms", 0),
                        "degraded": bool((snapshot.get("metrics") or {}).get("degraded")),
                    },
                )
            return {"ok": True, "snapshot": snapshot}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("SelfModelService: cognition recall failed: {}", exc)
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.COGNITION_RECALL_FAILED,
                    {**event_payload, "error": type(exc).__name__},
                )
            return {"ok": False, "reason": "cognition_recall_failed"}

    async def build_context(
        self,
        *,
        user_id: str,
        query: str = "",
        run_context: Optional[Any] = None,
        budget_chars: int = 2400,
    ) -> Dict[str, Any]:
        normalized_query = str(query or "").strip()
        if normalized_query:
            config = self._merged_config(user_id)
            policy = CognitiveRecallPolicy.from_config(config)
            session_id = str(getattr(run_context, "session_id", None) or "default")
            pool = await asyncio.to_thread(
                self._passive_candidate_pool,
                user_id=user_id,
                query=normalized_query,
                limit=policy.fast_candidate_limit,
            )
            proposals = self.memory_service.list_write_proposals(
                user_id=user_id,
                status="pending",
                limit=policy.fast_candidate_limit,
            ) if self.memory_service is not None else []
            cognition = self.project_cognition(
                user_id=user_id,
                entries=list(pool.get("candidates") or []) if pool.get("ok") else [],
                proposals=list(proposals or []),
                limit=policy.fast_candidate_limit,
            )
        else:
            result = await asyncio.to_thread(
                self.build_cognition_bundle,
                user_id=user_id,
                limit=120,
            )
            cognition = result.get("cognition") if result.get("ok") else {}
        items = list((cognition or {}).get("items") or [])
        if normalized_query:
            global_bundle = await asyncio.to_thread(self.build_cognition_bundle, user_id=user_id, limit=120)
            global_items = list((global_bundle.get("cognition") or {}).get("items") or [])
            seen = {item.get("cognition_id") for item in items}
            items.extend(item for item in global_items if item.get("cognition_id") not in seen)
        else:
            global_items = items
        current = [item for item in items if item.get("state") == "current"]
        evolving = [item for item in items if item.get("state") == "evolving"]
        uncertain = [item for item in items if item.get("state") == "uncertain"]
        active = {
            key: str(getattr(run_context, key, "") or "")
            for key in ("task_id", "run_id", "session_id")
            if getattr(run_context, key, None)
        } if run_context is not None else {}
        task_summary: Dict[str, Any] = {}
        task_id = active.get("task_id")
        if task_id and self.task_service is not None:
            try:
                task = self.task_service.get_task(task_id, user_id=user_id)
            except Exception:
                task = None
            if isinstance(task, dict):
                task_summary = {
                    "task_id": task_id,
                    "title": str(task.get("title") or ""),
                    "objective": str(task.get("objective") or ""),
                    "status": str(task.get("status") or ""),
                    "revision": task.get("revision"),
                }

        runtime = self.runtime_projection(user_id)
        environment = await self.environment.snapshot(user_id)
        from config import config as runtime_config
        observation_prompt = self.environment.prompt(environment, runtime_config.self_model.observation_chars)
        lines = [
            "Self model context:",
            "- Current cognition may guide continuity; uncertain cognition is not established fact.",
            "- Evolving items are plans or bounded state, not durable identity.",
        ]
        if task_summary:
            task_line = f"Active task: {task_summary['title']} [{task_summary['status']}]"
            if task_summary.get("objective"):
                task_line += f" - {task_summary['objective']}"
            lines.append(task_line)
        for heading, rows in (("Current cognition", current), ("Evolving commitments", evolving), ("Uncertainties", uncertain)):
            if not rows:
                continue
            lines.append(f"{heading}:")
            for item in rows[:10]:
                candidate = f"- [{item.get('domain')}] {item.get('content')}"
                if sum(len(line) + 1 for line in lines) + len(candidate) > max(400, int(budget_chars) // (2 if runtime else 1)):
                    break
                lines.append(candidate)
        prompt_text = "\n".join(lines) if len(lines) > 3 else ""
        if runtime:
            projection_lines = ["\nPersonal-space continuity (revisable data):", "Sources: " + ", ".join(runtime["coverage"])]
            sources = [(name, value) for name, value in runtime.items() if name != "coverage"]
            remaining = max(0, budget_chars - len(prompt_text) - sum(len(part) + 1 for part in projection_lines))
            # Reserve room for every source; a large task/history cannot hide attention.
            for index, (name, value) in enumerate(sources):
                allowance = remaining // (len(sources) - index)
                prefix = name + ": "
                encoded = json.dumps(value, ensure_ascii=False, default=str)
                marker = " ... [excerpt]"
                available = max(0, allowance - len(prefix) - 1)
                if len(encoded) > available:
                    encoded = encoded[:max(0, available - len(marker))] + marker if available >= len(marker) else ""
                line = prefix + encoded
                if len(line) + 1 <= remaining:
                    projection_lines.append(line)
                    remaining -= len(line) + 1
            prompt_text += "\n".join(projection_lines)
        revision_source = json.dumps({"items": items, "runtime": runtime, "environment": environment}, sort_keys=True, ensure_ascii=False, default=str)
        return {
            "version": "self_model.context.v1",
            "revision": hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16],
            "user_id": str(user_id),
            "active": active, "task": task_summary,
            "current": current[:10], "evolving": evolving[:10], "uncertain": uncertain[:10],
            "global_context": {
                "identity_source": "PromptAssembler core identity, customization and Soul",
                "cognition": [item for item in global_items if item.get("state") == "current"][:10],
                "commitments": [item for item in global_items if item.get("state") == "evolving"][:10],
                "authority": "governed Memory and live Runtime projections, not model declarations",
            },
            "situational_context": {
                "working": self.working_context(user_id), "active": active,
                "environmental_state": environment,
                "uncertain": uncertain[:10], "runtime": runtime,
            },
            "environment": environment,
            "observation_prompt": observation_prompt,
            "runtime": runtime,
            "prompt_text": prompt_text,
        }

    def runtime_projection(self, user_id: str) -> Dict[str, Any]:
        """Cover each owned source with bounded fields and explicit coverage."""
        result: Dict[str, Any] = {"coverage": {}}
        if self.task_service is not None:
            tasks = self.task_service.list_tasks(user_id=user_id, limit=100)
            active = [row for row in tasks if row.get("status") not in {"completed", "cancelled"} and row.get("source") not in {"ambient", "agent_inbox"}]
            result["tasks"] = [{"task_id": row["task_id"], "title": str(row.get("title") or "")[:160], "objective": str(row.get("objective") or "")[:400], "status": row["status"], "revision": row.get("revision")} for row in active[:8]]
            result["coverage"]["tasks"] = {"observed": len(tasks), "active": len(active), "included": len(result["tasks"])}
        if self.workflow_engine is not None:
            workflows = self.workflow_engine.list_runs(user_id=user_id, limit=100)
            result["workflows"] = [{key: row.get(key) for key in ("workflow_run_id", "task_id", "session_id", "status")} for row in workflows if row.get("status") not in {"completed", "cancelled"}][:8]
            result["coverage"]["workflows"] = {"observed": len(workflows), "included": len(result["workflows"])}
        if self.message_manager is not None:
            sessions = self.message_manager.list_sessions(user_id=user_id, limit=6)
            result["conversations"] = [{"session_id": row["session_id"], "title": str(row.get("title") or "")[:160], "last_message": str(row.get("last_message") or "")[:300], "last_activity": row.get("last_activity")} for row in sessions]
            result["coverage"]["conversations"] = {"included": len(sessions)}
        result["attention"] = self.working_context(user_id)
        # Live visibility has one independently refreshed model-visible block.
        result["attention"].pop("surface", None)
        result["coverage"]["attention"] = {"available": True}
        result["expressions"] = self.semantic_ui.context_projection(user_id)
        result["coverage"]["expressions"] = {"available": True}
        if self.agent_messages is not None:
            result["communication"] = self.agent_messages.communication_context(user_id)
            result["coverage"]["communication"] = {"available": True}
        return result if len(result) > 1 else {}
