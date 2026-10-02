"""Unified, read-only self-model projection for the Promethea runtime."""

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
    ) -> None:
        self.memory_service = memory_service
        self.task_service = task_service
        self.capability_service = capability_service
        self.config_service = config_service
        self.event_emitter = event_emitter
        self.llm_client = llm_client
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.self_model_path = self.workspace_root / "memory" / "self_model.json"

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
                self._candidate_pool,
                user_id=user_id,
                session_id=session_id,
                query=normalized_query,
                limit=policy.fast_candidate_limit,
                run_context=run_context,
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
                if sum(len(line) + 1 for line in lines) + len(candidate) > max(600, int(budget_chars)):
                    break
                lines.append(candidate)
        prompt_text = "\n".join(lines) if len(lines) > 3 else ""
        revision_source = "|".join(str(item.get("cognition_id") or "") + str(item.get("updated_at") or "") for item in items)
        return {
            "version": "self_model.context.v1",
            "revision": hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16],
            "user_id": str(user_id),
            "active": active, "task": task_summary,
            "current": current[:10], "evolving": evolving[:10], "uncertain": uncertain[:10],
            "prompt_text": prompt_text,
        }
