from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from .events import EventEmitter
from .protocol import EventType
from .reasoning_budget import ReasoningBudgetLedger
from .reasoning_debug import ReasoningDebugSnapshotWriter
from .reasoning_policy import ReasoningPolicyResolver
from .reasoning_template_memory import ReasoningTemplateMemory
from .reasoning_tree_store import ReasoningTreeHistoryStore
from .reasoning_tree_runtime import ReasoningTreeRuntime
from .reasoning_tool_runtime import ReasoningToolCatalogResolver, ReasoningToolQualityTracker
from .tool_service import ToolInvocationContext
from .tool_strategy import ToolStrategyEngine
from .reasoning_models import ReasoningNode, ReasoningTree
from .reasoning_utils import (
    extract_json_object,
    format_recent_messages,
    map_plan_steps_to_moirai,
    merge_steps,
    safe_user_segment,
    stringify_observation,
    to_bool,
    truncate_text,
)
from .reasoning_state_machine import (
    FAILED,
    PENDING,
    RUNNING,
    SKIPPED,
    SUCCEEDED,
    WAITING_HUMAN,
    WAITING_TOOL,
    TERMINAL_STATES,
)


class ReasoningService:
    """Runtime reasoning tree service."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        tool_service: Optional[Any] = None,
        workflow_engine: Optional[Any] = None,
        config_service: Optional[Any] = None,
        template_memory: Optional[ReasoningTemplateMemory] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core
        self.memory_service = memory_service
        self.tool_service = tool_service
        self.workflow_engine = workflow_engine
        self.config_service = config_service
        if template_memory is not None:
            self.template_memory = template_memory
        else:
            try:
                self.template_memory = ReasoningTemplateMemory()
            except Exception as e:
                logger.warning("ReasoningService: template memory init failed, disabled: {}", e)
                self.template_memory = None
        self._active_trees: Dict[str, ReasoningTree] = {}
        self._pending_outcomes: Dict[str, Dict[str, Any]] = {}
        self._completed_trees: Dict[str, Dict[str, Any]] = {}
        self._pending_human_reviews: Dict[str, Dict[str, Any]] = {}
        self._runtime_controls: Dict[str, Dict[str, Any]] = {}
        self._completed_runs = 0
        self._failed_runs = 0
        self.tool_strategy = ToolStrategyEngine()
        self.budget_ledger = ReasoningBudgetLedger()
        self.tree_history = ReasoningTreeHistoryStore()
        self.policy_resolver = ReasoningPolicyResolver()
        self.tree_runtime = ReasoningTreeRuntime()
        self.debug_snapshot_writer = ReasoningDebugSnapshotWriter()
        self.tool_quality = ReasoningToolQualityTracker()
        self.tool_catalog = ReasoningToolCatalogResolver()
        self._tool_selection_stats: Dict[str, Any] = {
            "total": 0,
            "llm_selected": 0,
            "strategy_fallback": 0,
            "no_tool": 0,
            "tool_observation_ok": 0,
            "tool_observation_failed": 0,
        }

    def is_enabled(self, user_id: Optional[str] = None) -> bool:
        policy = self._resolve_policy(user_id=user_id, user_config=None)
        return bool(policy.get("enabled", True)) and self.conversation_core is not None

    def get_stats(self) -> Dict[str, Any]:
        enabled = False
        try:
            enabled = self.is_enabled()
        except Exception:
            enabled = False
        return {
            "enabled": enabled,
            "active_trees": len(self._active_trees),
            "pending_outcomes": len(self._pending_outcomes),
            "completed_trees": len(self._completed_trees),
            "pending_human_reviews": len(self._pending_human_reviews),
            "controlled_trees": len(self._runtime_controls),
            "completed_runs": self._completed_runs,
            "failed_runs": self._failed_runs,
            "tool_selection": dict(self._tool_selection_stats),
            "tool_quality": self._runtime_tool_quality_hints(limit=8),
        }

    def list_runtime_trees(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        include_pending: bool = True,
        limit: int = 20,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        seen_tree_ids: set[str] = set()

        def add_row(row: Dict[str, Any]) -> None:
            tree_id = str(row.get("tree_id", "") or "")
            if tree_id and tree_id in seen_tree_ids:
                return
            if tree_id:
                seen_tree_ids.add(tree_id)
            rows.append(row)

        for tree in self._active_trees.values():
            if user_id and tree.user_id != user_id:
                continue
            if session_id and tree.session_id != session_id:
                continue
            add_row(self._serialize_tree(tree, include_nodes=False))
        if include_pending:
            for item in self._pending_outcomes.values():
                payload = item.get("tree", {}) if isinstance(item, dict) else {}
                if not isinstance(payload, dict):
                    continue
                if user_id and str(payload.get("user_id", "")) != str(user_id):
                    continue
                if session_id and str(payload.get("session_id", "")) != str(session_id):
                    continue
                add_row(self._serialize_tree_payload(payload, include_nodes=False))
            for payload in self._completed_trees.values():
                if not isinstance(payload, dict):
                    continue
                if user_id and str(payload.get("user_id", "")) != str(user_id):
                    continue
                if session_id and str(payload.get("session_id", "")) != str(session_id):
                    continue
                add_row(self._serialize_tree_payload(payload, include_nodes=False))
            persisted_limit = max(max(1, int(limit)) * 3, 50)
            for payload in self.tree_history.list(
                user_id=user_id,
                session_id=session_id,
                limit=persisted_limit,
            ):
                if not isinstance(payload, dict):
                    continue
                if user_id and str(payload.get("user_id", "")) != str(user_id):
                    continue
                add_row(self._serialize_tree_payload(payload, include_nodes=False))
        rows.sort(key=lambda it: float(it.get("updated_at") or 0.0), reverse=True)
        return {"items": rows[: max(1, int(limit))], "total": len(rows)}

    def get_runtime_tree(
        self,
        *,
        tree_id: str,
        user_id: Optional[str] = None,
        include_nodes: bool = True,
    ) -> Optional[Dict[str, Any]]:
        tree = self._active_trees.get(tree_id)
        if tree:
            if user_id and tree.user_id != user_id:
                return None
            return self._serialize_tree(tree, include_nodes=include_nodes)
        outcome = self._pending_outcomes.get(tree_id)
        if outcome:
            payload = outcome.get("tree", {}) if isinstance(outcome, dict) else {}
        else:
            payload = self._completed_trees.get(tree_id, {})
            if not payload:
                payload = self.tree_history.load(tree_id=tree_id, user_id=user_id)
                if payload:
                    self._completed_trees[str(tree_id)] = dict(payload)
        if not isinstance(payload, dict):
            return None
        if user_id and str(payload.get("user_id", "")) != str(user_id):
            return None
        return self._serialize_tree_payload(payload, include_nodes=include_nodes)

    def request_stop(
        self,
        *,
        tree_id: str,
        user_id: Optional[str],
        reason: str = "",
    ) -> Dict[str, Any]:
        tree = self._active_trees.get(tree_id)
        if not tree:
            return {"status": "missing", "tree_id": tree_id}
        if user_id and tree.user_id != user_id:
            return {"status": "forbidden", "tree_id": tree_id}
        control = self._runtime_controls.setdefault(tree_id, {})
        control["stop_requested"] = True
        control["stop_reason"] = str(reason or "").strip()
        control["stop_requested_at"] = time.time()
        tree.stats["stop_requested"] = True
        tree.updated_at = time.time()
        return {"status": "accepted", "tree_id": tree_id, "stop_requested": True}

    def add_steering_note(
        self,
        *,
        tree_id: str,
        user_id: Optional[str],
        note: str,
    ) -> Dict[str, Any]:
        clean = str(note or "").strip()
        if not clean:
            return {"status": "invalid", "reason": "empty_note", "tree_id": tree_id}
        tree = self._active_trees.get(tree_id)
        if not tree:
            return {"status": "missing", "tree_id": tree_id}
        if user_id and tree.user_id != user_id:
            return {"status": "forbidden", "tree_id": tree_id}
        control = self._runtime_controls.setdefault(tree_id, {})
        notes = control.setdefault("steering_notes", [])
        entry = {"note": clean, "created_at": time.time()}
        notes.append(entry)
        tree.stats["pending_steering_notes"] = len(notes)
        tree.stats["steering_notes_total"] = int(tree.stats.get("steering_notes_total", 0)) + 1
        tree.updated_at = time.time()
        return {"status": "accepted", "tree_id": tree_id, "pending_notes": len(notes)}

    def _is_stop_requested(self, tree_id: str) -> bool:
        control = self._runtime_controls.get(tree_id, {})
        return bool(control.get("stop_requested"))

    def _consume_steering_notes(self, tree_id: str) -> List[Dict[str, Any]]:
        control = self._runtime_controls.get(tree_id)
        if not control:
            return []
        notes = control.get("steering_notes")
        if not isinstance(notes, list) or not notes:
            return []
        consumed = list(notes)
        control["steering_notes"] = []
        return consumed

    def _serialize_tree_payload(
        self,
        payload: Dict[str, Any],
        *,
        include_nodes: bool,
    ) -> Dict[str, Any]:
        tree_id = str(payload.get("tree_id", "") or "")
        return self.tree_runtime.serialize_tree_payload(
            payload,
            include_nodes=include_nodes,
            control=self._runtime_controls.get(tree_id, {}),
        )

    def _serialize_tree(self, tree: ReasoningTree, *, include_nodes: bool) -> Dict[str, Any]:
        return self.tree_runtime.serialize_tree(
            tree,
            include_nodes=include_nodes,
            control=self._runtime_controls.get(tree.tree_id, {}),
        )

    def record_outcome(
        self,
        *,
        tree_id: Optional[str],
        success: bool,
        assistant_output: str = "",
    ) -> bool:
        # Backward-compatible adapter. New flow should call `assess_outcome`.
        if not tree_id:
            return False
        data = self._pending_outcomes.pop(tree_id, None)
        if not data or not success:
            return False
        self._remember_completed_tree(data)
        if not self.template_memory:
            return False
        try:
            self.template_memory.record_success(
                user_id=data.get("user_id", "default_user"),
                session_id=data.get("session_id", ""),
                user_message=data.get("user_message", ""),
                assistant_output=assistant_output or "",
                gate=data.get("gate", {}) or {},
                policy=data.get("policy", {}) or {},
                tree_payload=data.get("tree", {}) or {},
            )
            return True
        except Exception as e:
            logger.debug("ReasoningService: record_outcome failed: {}", e)
            return False

    async def assess_outcome(
        self,
        *,
        tree_id: Optional[str],
        assistant_output: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        allow_human_review: bool = True,
    ) -> Dict[str, Any]:
        if not tree_id:
            return {"status": "ignored", "reason": "missing_tree_id"}
        data = self._pending_outcomes.pop(tree_id, None)
        if not data:
            return {"status": "ignored", "reason": "missing_pending_outcome"}
        self._remember_completed_tree(data)

        verdict = await self._judge_task_success(
            user_message=str(data.get("user_message", "") or ""),
            assistant_output=assistant_output or "",
            gate=data.get("gate", {}) or {},
            policy=data.get("policy", {}) or {},
            tree_stats=(data.get("tree", {}) or {}).get("stats", {}) or {},
            user_config=user_config,
            user_id=user_id,
        )
        outcome = str(verdict.get("outcome", "unsure") or "unsure").strip().lower()
        confidence = float(verdict.get("confidence", 0.0) or 0.0)

        if outcome == "success" and confidence >= 0.75:
            if self.template_memory:
                self.template_memory.record_success(
                    user_id=str(data.get("user_id", user_id or "default_user")),
                    session_id=str(data.get("session_id", "") or ""),
                    user_message=str(data.get("user_message", "") or ""),
                    assistant_output=assistant_output or "",
                    gate=data.get("gate", {}) or {},
                    policy=data.get("policy", {}) or {},
                    tree_payload=data.get("tree", {}) or {},
                )
            return {
                "status": "recorded",
                "outcome": outcome,
                "confidence": confidence,
                "reason": str(verdict.get("reason", "") or ""),
            }

        if outcome == "failure" and confidence >= 0.75:
            return {
                "status": "discarded",
                "outcome": outcome,
                "confidence": confidence,
                "reason": str(verdict.get("reason", "") or ""),
            }

        if not allow_human_review:
            return {
                "status": "discarded",
                "outcome": "unsure",
                "confidence": confidence,
                "reason": "human_review_disabled",
            }

        review_id = f"reasoning_review_{uuid.uuid4().hex}"
        self._pending_human_reviews[review_id] = {
            **data,
            "assistant_output": assistant_output or "",
            "judge": verdict,
            "created_at": time.time(),
        }
        return {
            "status": "needs_confirmation",
            "review_id": review_id,
            "outcome": outcome,
            "confidence": confidence,
            "reason": str(verdict.get("reason", "") or ""),
        }

    def confirm_outcome(
        self,
        *,
        review_id: str,
        approve: bool,
    ) -> bool:
        if not review_id:
            return False
        data = self._pending_human_reviews.pop(review_id, None)
        if not data:
            return False
        self._remember_completed_tree(data)
        if not approve:
            return True
        if not self.template_memory:
            return False
        try:
            self.template_memory.record_success(
                user_id=str(data.get("user_id", "default_user")),
                session_id=str(data.get("session_id", "") or ""),
                user_message=str(data.get("user_message", "") or ""),
                assistant_output=str(data.get("assistant_output", "") or ""),
                gate=data.get("gate", {}) or {},
                policy=data.get("policy", {}) or {},
                tree_payload=data.get("tree", {}) or {},
            )
            return True
        except Exception as e:
            logger.debug("ReasoningService: confirm_outcome failed: {}", e)
            return False

    def _remember_completed_tree(self, data: Dict[str, Any]) -> None:
        payload = data.get("tree", {}) if isinstance(data, dict) else {}
        if not isinstance(payload, dict):
            return
        self.tree_history.remember(payload, self._completed_trees)

    def _resolve_policy(
        self,
        *,
        user_id: Optional[str],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        loader = None
        if self.config_service:
            loader = self.config_service.get_merged_config
        return self.policy_resolver.resolve(
            user_id=user_id,
            user_config=user_config,
            config_loader=loader,
        )

    def _create_tree(self, *, session_id: str, user_id: str, root_goal: str) -> ReasoningTree:
        return self.tree_runtime.create_tree(session_id=session_id, user_id=user_id, root_goal=root_goal)

    def _add_node(
        self,
        tree: ReasoningTree,
        *,
        parent_id: Optional[str],
        kind: str,
        title: str,
        prompt: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningNode:
        return self.tree_runtime.add_node(
            tree,
            parent_id=parent_id,
            kind=kind,
            title=title,
            prompt=prompt,
            metadata=metadata,
        )

    def _transition_node_status(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        target: str,
        reason: str = "",
        checkpoint: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tree_runtime.transition_node_status(
            tree=tree,
            node=node,
            target=target,
            reason=reason,
            checkpoint=checkpoint,
        )

    def _mark_node_succeeded(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        observation: str,
        evidence: Optional[List[str]] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tree_runtime.mark_node_succeeded(
            tree=tree,
            node=node,
            observation=observation,
            evidence=evidence,
            result=result,
        )

    def _resume_node_from_waiting_tool(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        note: str = "tool_observation_ready",
    ) -> None:
        self.tree_runtime.resume_node_from_waiting_tool(tree=tree, node=node, note=note)

    def _resume_node_from_waiting_human(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        approved: bool,
    ) -> None:
        self.tree_runtime.resume_node_from_waiting_human(tree=tree, node=node, approved=approved)

    def _snapshot_node(self, node: ReasoningNode) -> Dict[str, Any]:
        return self.tree_runtime.snapshot_node(node)

    def _node_depth(self, tree: ReasoningTree, node_id: Optional[str]) -> int:
        return self.tree_runtime.node_depth(tree, node_id)

    async def _emit(self, event: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        try:
            await self.event_emitter.emit(event, payload)
        except Exception as e:
            logger.debug("ReasoningService emit failed {}: {}", event, e)

    def _extract_run_context_fields(
        self,
        run_context: Optional[Any],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if run_context is not None:
            trace_id = getattr(run_context, "trace_id", None)
            request_id = getattr(run_context, "request_id", None)
            session_value = getattr(run_context, "session_id", None)
            user_value = getattr(run_context, "user_id", None)
            session_state = getattr(run_context, "session_state", None)
            if session_value is None and session_state is not None:
                session_value = getattr(session_state, "session_id", None)
            if user_value is None and session_state is not None:
                user_value = getattr(session_state, "user_id", None)
            if trace_id is None and session_state is not None:
                trace_id = getattr(session_state, "trace_id", None)
            if trace_id:
                data["trace_id"] = str(trace_id)
            if request_id:
                data["request_id"] = str(request_id)
            if session_value:
                data["session_id"] = str(session_value)
            if user_value:
                data["user_id"] = str(user_value)
        if session_id and "session_id" not in data:
            data["session_id"] = str(session_id)
        if user_id and "user_id" not in data:
            data["user_id"] = str(user_id)
        return data
    async def _emit_node(self, tree: ReasoningTree, node: ReasoningNode, event: EventType) -> None:
        await self._emit(
            event,
            {
                "tree_id": tree.tree_id,
                "session_id": tree.session_id,
                "user_id": tree.user_id,
                "node_id": node.node_id,
                "parent_id": node.parent_id,
                "kind": node.kind,
                "title": node.title,
                "status": node.status,
            },
        )

    async def run(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        base_system_prompt: str,
        user_config: Optional[Dict[str, Any]] = None,
        run_context: Optional[Any] = None,
        force_reasoning: bool = False,
    ) -> Dict[str, Any]:
        policy = self._resolve_policy(user_id=user_id, user_config=user_config)
        if (
            not policy["enabled"]
            or not self.conversation_core
            or policy.get("mode") != "react_tot"
        ):
            return {"used_reasoning": False}

        gate = await self._gate_reasoning(
            user_message=user_message,
            recent_messages=recent_messages,
            user_config=user_config,
            user_id=user_id,
        )
        template_match = {"matched": False, "score": 0.0, "template": None}
        strategy_hints: Dict[str, Any] = {}
        if self.template_memory:
            try:
                template_match = self.template_memory.match_template(
                    user_id=user_id,
                    task=user_message,
                )
                strategy_hints = self.template_memory.get_strategy_hints(user_id=user_id)
            except Exception as e:
                logger.debug("ReasoningService: template memory unavailable: {}", e)

        is_complex = self._to_bool(gate.get("needs_reasoning", False), default=False)
        if force_reasoning and not is_complex:
            gate = dict(gate)
            gate["needs_reasoning"] = True
            gate["reason"] = str(gate.get("reason") or "prompt_policy_requested_reasoning")
            gate["source"] = "prompt_policy"
            is_complex = True
        needs_memory = self._to_bool(gate.get("needs_memory", False), default=False)
        needs_tools = self._to_bool(gate.get("needs_tools", False), default=False)
        merged_hints = dict(strategy_hints or {})
        if template_match.get("matched"):
            merged_hints["template_matched"] = True
            merged_hints["template_score"] = float(template_match.get("score", 0.0) or 0.0)
        run_context_fields = self._extract_run_context_fields(
            run_context,
            session_id=session_id,
            user_id=user_id,
        )

        # Keep reasoning as an explicit complexity gate.
        # Memory/tool usage should remain independent capabilities and may run
        # in non-reasoning path (for example, direct memory recall in
        # ConversationService).
        if not is_complex:
            return {"used_reasoning": False, "gate": gate}

        tree = self._create_tree(session_id=session_id, user_id=user_id, root_goal=user_message)
        self._active_trees[tree.tree_id] = tree
        self._runtime_controls[tree.tree_id] = {
            "stop_requested": False,
            "stop_reason": "",
            "steering_notes": [],
        }
        start_payload = {
            "tree_id": tree.tree_id,
            "session_id": session_id,
            "user_id": user_id,
            "goal": user_message,
            "gate": gate,
            "mode": "tot_react" if is_complex else "react_only",
            **run_context_fields,
        }
        await self._emit(EventType.REASONING_START, start_payload)
        await self._emit(EventType.REASONING_STARTED, start_payload)
        try:
            steps: List[Dict[str, Any]] = []
            template_steps: List[Dict[str, Any]] = []
            if template_match.get("matched"):
                tmpl = template_match.get("template") or {}
                raw_steps = tmpl.get("steps", []) if isinstance(tmpl, dict) else []
                if isinstance(raw_steps, list):
                    for step in raw_steps[: policy["plan_max_steps"]]:
                        if not isinstance(step, dict):
                            continue
                        template_steps.append(
                            {
                                "title": str(step.get("title", "")).strip() or "template step",
                                "goal": str(step.get("goal", "")).strip() or str(step.get("title", "")).strip() or "continue",
                                "requires_memory": self._to_bool(step.get("requires_memory", False), default=False),
                                "memory_query": str(step.get("memory_query", "")).strip(),
                                "requires_tools": self._to_bool(step.get("requires_tools", False), default=False),
                                "tool_intent": str(step.get("tool_intent", "")).strip(),
                                "notes": str(step.get("notes", "")).strip(),
                            }
                        )
            if is_complex:
                generated_steps = await self._plan_steps(
                    tree=tree,
                    user_message=user_message,
                    recent_messages=recent_messages,
                    user_config=user_config,
                    user_id=user_id,
                    policy=policy,
                    strategy_hints=merged_hints,
                    max_candidates=max(
                        policy["plan_max_steps"],
                        policy["beam_width"] * policy["branch_factor"],
                    ),
                )
                steps = self._merge_steps(template_steps, generated_steps, policy["plan_max_steps"])
            else:
                steps = template_steps[:1] if template_steps else []
                if not steps:
                    steps = [
                        {
                            "title": "direct react loop",
                            "goal": user_message,
                            "requires_memory": needs_memory,
                            "memory_query": user_message if needs_memory else "",
                            "requires_tools": needs_tools,
                            "tool_intent": user_message,
                            "notes": "simple task, skip ToT planning and execute ReAct directly",
                        }
                    ]
            if not steps:
                tree.status = SKIPPED
                return {"used_reasoning": False, "gate": gate}

            moirai_run_id = await self._export_plan_to_moirai(
                tree=tree,
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                steps=steps,
                gate=gate,
                policy=policy,
                run_context=run_context,
                user_config=user_config,
            )

            initial_nodes: List[str] = []
            for step in steps:
                if len(tree.nodes) >= policy["max_nodes"]:
                    break
                node = self._add_node(
                    tree,
                    parent_id=tree.root_node_id,
                    kind="thought",
                    title=step.get("title") or "plan step",
                    prompt=json.dumps(step, ensure_ascii=False),
                    metadata=step,
                )
                initial_nodes.append(node.node_id)

            if is_complex:
                frontier = await self._select_beam_nodes(
                    tree=tree,
                    candidate_node_ids=initial_nodes,
                    user_message=user_message,
                    user_config=user_config,
                    user_id=user_id,
                    policy=policy,
                    stage="tot_initial",
                )
            else:
                frontier = initial_nodes[:1]

            iteration_budget = policy["max_iterations"] if is_complex else 1
            stopped_by_user = False

            while frontier and tree.stats["iterations"] < iteration_budget:
                if self._is_stop_requested(tree.tree_id):
                    stopped_by_user = True
                    break
                if self.budget_ledger.should_stop_reasoning(self.budget_ledger.build(tree, policy)):
                    tree.stats["termination"] = "budget_exhausted"
                    break
                next_candidates: List[str] = []
                for node_id in frontier:
                    if self._is_stop_requested(tree.tree_id):
                        stopped_by_user = True
                        break
                    if self.budget_ledger.should_stop_reasoning(self.budget_ledger.build(tree, policy)):
                        tree.stats["termination"] = "budget_exhausted"
                        break
                    tree.stats["iterations"] += 1
                    extra_steps = await self._execute_step(
                        tree=tree,
                        node_id=node_id,
                        session_id=session_id,
                        user_id=user_id,
                        user_message=user_message,
                        recent_messages=recent_messages,
                        user_config=user_config,
                        policy=policy,
                        run_context=run_context,
                    )
                    for step in extra_steps:
                        if self.budget_ledger.should_avoid_external_actions(self.budget_ledger.build(tree, policy)):
                            break
                        if self._node_depth(tree, node_id) >= policy["max_depth"]:
                            break
                        if len(tree.nodes) >= policy["max_nodes"]:
                            break
                        extra_node = self._add_node(
                            tree,
                            parent_id=node_id,
                            kind="thought",
                            title=step.get("title") or "follow-up thought",
                            prompt=json.dumps(step, ensure_ascii=False),
                            metadata=step,
                        )
                        next_candidates.append(extra_node.node_id)
                    if tree.stats["iterations"] >= iteration_budget:
                        break

                if not next_candidates:
                    break
                if is_complex:
                    frontier = await self._select_beam_nodes(
                        tree=tree,
                        candidate_node_ids=next_candidates,
                        user_message=user_message,
                        user_config=user_config,
                        user_id=user_id,
                        policy=policy,
                        stage="tot_expand",
                    )
                else:
                    frontier = []

            runtime_outcome: Dict[str, Any] = {
                "status": "success",
                "reason": "",
                "confidence": 1.0,
                "suggestion": "",
            }
            if stopped_by_user:
                tree.status = SKIPPED
                tree.stats["termination"] = "stopped_by_user"
            else:
                runtime_outcome = await self._decide_runtime_outcome(
                    user_message=user_message,
                    tree=tree,
                    policy=policy,
                    iteration_budget=iteration_budget,
                    user_config=user_config,
                    user_id=user_id,
                )
                outcome_status = str(runtime_outcome.get("status", "success") or "success")
                if outcome_status == "failed":
                    tree.status = FAILED
                    tree.stats["termination"] = "runtime_failed"
                else:
                    tree.status = SUCCEEDED
                    if tree.stats.get("termination") != "budget_exhausted":
                        tree.stats["termination"] = (
                            "max_iterations"
                            if tree.stats["iterations"] >= iteration_budget
                            else "completed"
                        )
                tree.stats["runtime_outcome"] = {
                    "status": outcome_status,
                    "reason": str(runtime_outcome.get("reason", "") or ""),
                    "confidence": float(runtime_outcome.get("confidence", 0.0) or 0.0),
                    "suggestion": str(runtime_outcome.get("suggestion", "") or ""),
                }
            reasoning_summary = await self._summarize_tree(
                tree=tree,
                user_message=user_message,
                user_config=user_config,
                user_id=user_id,
            )
            final_prompt = base_system_prompt.strip()
            if reasoning_summary:
                extra = (
                    "Internal reasoning context for answer synthesis. Use it to improve the answer, "
                    "but do not mention this reasoning process, hidden protocols, JSON schemas, or tool-call formatting explicitly.\n"
                    "When deep reasoning was used, the final answer should preserve the value of that work: "
                    "give a clear conclusion, the main supporting logic, important evidence or uncertainty limits, "
                    "tradeoffs/risks where relevant, and practical next steps. Do not collapse a complex reasoning result "
                    "into a one-line answer unless the user explicitly asked for brevity.\n"
                    f"{reasoning_summary}"
                )
                final_prompt = f"{final_prompt}\n\n{extra}" if final_prompt else extra
            if tree.status == FAILED:
                fail_reason = str(runtime_outcome.get("reason", "") or "").strip()
                fail_suggestion = str(runtime_outcome.get("suggestion", "") or "").strip()
                blocker_line = f"Blocker: {fail_reason}" if fail_reason else "Blocker: task appears infeasible under current runtime constraints."
                suggest_line = (
                    f"Suggestion: {fail_suggestion}"
                    if fail_suggestion
                    else "Suggestion: explain attempted paths and ask user for a decisive next action."
                )
                fail_instruction = (
                    "Execution encountered persistent blockers. "
                    "Be explicit with the user about what was attempted and why the task cannot continue automatically right now.\n"
                    f"{blocker_line}\n"
                    f"{suggest_line}"
                )
                final_prompt = f"{final_prompt}\n\n{fail_instruction}" if final_prompt else fail_instruction

            tree.updated_at = time.time()
            if tree.status == FAILED:
                self._failed_runs += 1
            else:
                self._completed_runs += 1
            complete_payload = {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "status": tree.status,
                "stats": tree.stats,
                **run_context_fields,
            }
            await self._emit(EventType.REASONING_COMPLETE, complete_payload)
            await self._emit(EventType.REASONING_FINISHED, complete_payload)
            await self._write_debug_snapshot(tree, user_id=user_id, policy=policy)
            self._pending_outcomes[tree.tree_id] = {
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "gate": gate,
                "policy": policy,
                "moirai_run_id": moirai_run_id,
                "template_match": {
                    "matched": bool(template_match.get("matched")),
                    "score": float(template_match.get("score", 0.0) or 0.0),
                    "template_id": (
                        (template_match.get("template") or {}).get("template_id")
                        if isinstance(template_match.get("template"), dict)
                        else None
                    ),
                },
                "tree": {
                    "tree_id": tree.tree_id,
                    "session_id": tree.session_id,
                    "user_id": tree.user_id,
                    "root_goal": tree.root_goal,
                    "status": tree.status,
                    "created_at": tree.created_at,
                    "updated_at": tree.updated_at,
                    "stats": dict(tree.stats),
                    "root_node_id": tree.root_node_id,
                    "nodes": [asdict(node) for node in tree.nodes.values()],
                },
            }
            if len(self._pending_outcomes) > 512:
                oldest = next(iter(self._pending_outcomes.keys()))
                self._pending_outcomes.pop(oldest, None)
            return {
                "used_reasoning": True,
                "tree_id": tree.tree_id,
                "system_prompt": final_prompt,
                "reasoning_summary": reasoning_summary,
                "plan_steps": steps,
                "gate": gate,
                "template_match": {
                    "matched": bool(template_match.get("matched")),
                    "score": float(template_match.get("score", 0.0) or 0.0),
                },
                "moirai_run_id": moirai_run_id,
                "status": tree.status,
                "runtime_outcome": dict(runtime_outcome or {}),
            }
        except Exception:
            tree.status = FAILED
            self._failed_runs += 1
            self._pending_outcomes.pop(tree.tree_id, None)
            await self._emit(
                EventType.REASONING_ERROR,
                {
                    "tree_id": tree.tree_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": tree.status,
                    **run_context_fields,
                },
            )
            await self._write_debug_snapshot(tree, user_id=user_id, policy=policy)
            raise
        finally:
            self._active_trees.pop(tree.tree_id, None)
            self._runtime_controls.pop(tree.tree_id, None)

    async def _gate_reasoning(
        self,
        *,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        heuristic = self._heuristic_gate(user_message)
        # Fast path: for clearly simple turns, skip the extra LLM gate call.
        if (
            not self._to_bool(heuristic.get("needs_reasoning"), default=False)
            and not self._to_bool(heuristic.get("needs_memory"), default=False)
            and not self._to_bool(heuristic.get("needs_tools"), default=False)
        ):
            return heuristic
        prompt = (
            "You are a reasoning gate. Decide whether the user task needs an explicit "
            "system-level reasoning tree before answering. Return strict JSON with keys: "
            "needs_reasoning, complexity, needs_memory, needs_tools, reason."
        )
        recent_text = self._format_recent_messages(recent_messages)
        llm_result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"User message:\n{user_message}\n\n"
                        f"Recent context:\n{recent_text}\n\n"
                        f"Heuristic hint:\n{json.dumps(heuristic, ensure_ascii=False)}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not llm_result:
            return heuristic
        merged = dict(heuristic)
        merged.update({k: v for k, v in llm_result.items() if v is not None})
        merged["needs_reasoning"] = self._to_bool(
            merged.get("needs_reasoning", heuristic["needs_reasoning"]),
            default=heuristic["needs_reasoning"],
        )
        merged["needs_memory"] = self._to_bool(
            merged.get("needs_memory", heuristic["needs_memory"]),
            default=heuristic["needs_memory"],
        )
        merged["needs_tools"] = self._to_bool(
            merged.get("needs_tools", heuristic["needs_tools"]),
            default=heuristic["needs_tools"],
        )
        return merged

    def _heuristic_gate(self, user_message: str) -> Dict[str, Any]:
        text = (user_message or "").strip().lower()
        multi_step_markers = (
            "step by step",
            "plan",
            "debug",
            "compare",
            "decision",
            "architecture",
            "design",
            "investigate",
            "troubleshoot",
            "tradeoff",
            "implementation",
        )
        tool_markers = ("tool", "browser", "file", "command", "shell", "run", "search")
        memory_markers = ("my preference", "remember", "history", "earlier", "before")
        needs_reasoning = (
            len(text) > 120
            or any(marker in text for marker in multi_step_markers)
            or text.count("\n") >= 2
        )
        return {
            "needs_reasoning": needs_reasoning,
            "complexity": "high"
            if len(text) > 240
            else "medium"
            if needs_reasoning
            else "low",
            "needs_memory": any(marker in text for marker in memory_markers),
            "needs_tools": any(marker in text for marker in tool_markers),
            "reason": "heuristic",
        }

    async def _plan_steps(
        self,
        *,
        tree: ReasoningTree,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        policy: Dict[str, Any],
        strategy_hints: Optional[Dict[str, Any]] = None,
        max_candidates: Optional[int] = None,
        observation_context: str = "",
    ) -> List[Dict[str, Any]]:
        candidate_limit = max(1, int(max_candidates or policy["plan_max_steps"]))
        plan_prompt = (
            "Generate candidate Thought nodes for Tree-of-Thought reasoning. "
            "A Thought is a compact sub-goal that can be executed via ReAct. "
            "Return strict JSON: "
            "{\"steps\":[{\"title\":string,\"goal\":string,\"requires_memory\":bool,"
            "\"memory_query\":string,\"requires_tools\":bool,\"tool_intent\":string,"
            "\"notes\":string}]}. Keep at most "
            f"{candidate_limit} steps."
        )
        result = await self._call_json(
            [
                {"role": "system", "content": plan_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{user_message}\n\n"
                        f"Recent context:\n{self._format_recent_messages(recent_messages)}\n\n"
                        f"Historical strategy hints:\n{json.dumps(strategy_hints or {}, ensure_ascii=False)}\n\n"
                        f"Current observations:\n{self._truncate_text(observation_context, 2500)}\n\n"
                        f"Current tree stats:\n{json.dumps(tree.stats, ensure_ascii=False)}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        steps = result.get("steps", []) if isinstance(result, dict) else []
        if not isinstance(steps, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for step in steps[:candidate_limit]:
            if not isinstance(step, dict):
                continue
            normalized.append(
                {
                    "title": str(step.get("title", "")).strip() or "thought step",
                    "goal": str(step.get("goal", "")).strip() or str(step.get("title", "")).strip() or "continue",
                    "requires_memory": self._to_bool(step.get("requires_memory", False), default=False),
                    "memory_query": str(step.get("memory_query", "")).strip(),
                    "requires_tools": self._to_bool(step.get("requires_tools", False), default=False),
                    "tool_intent": str(step.get("tool_intent", "")).strip(),
                    "notes": str(step.get("notes", "")).strip(),
                }
            )
        return normalized

    async def _execute_step(
        self,
        *,
        tree: ReasoningTree,
        node_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        policy: Dict[str, Any],
        run_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        node = tree.nodes[node_id]
        if self._is_stop_requested(tree.tree_id):
            return []
        if node.status in TERMINAL_STATES:
            return []

        if node.status == PENDING:
            self._transition_node_status(
                tree=tree,
                node=node,
                target=RUNNING,
                reason="execute_step_start",
                checkpoint={"phase": "start"},
            )
        elif node.status == WAITING_TOOL:
            self._resume_node_from_waiting_tool(tree=tree, node=node)
        elif node.status == WAITING_HUMAN:
            # Current runtime path has no persisted human-review queue for nodes yet,
            # so resume defaults to approved. Future workflow can override.
            self._resume_node_from_waiting_human(tree=tree, node=node, approved=True)
            if node.status == SKIPPED:
                return []
        elif node.status != RUNNING:
            self._transition_node_status(
                tree=tree,
                node=node,
                target=RUNNING,
                reason="recover_to_running",
            )

        await self._emit_node(tree, node, EventType.REASONING_NODE_CREATED)
        observations: List[str] = []
        step = dict(node.metadata)
        steering_notes = self._consume_steering_notes(tree.tree_id)
        if steering_notes:
            note_lines: List[str] = []
            for entry in steering_notes:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("note", "") or "").strip()
                if text:
                    note_lines.append(f"- {text}")
            if note_lines:
                steering_observation = "User steering guidance:\n" + "\n".join(note_lines)
                observations.append(steering_observation)
                step["steering_guidance"] = "\n".join(note_lines)
                node.metadata["steering_guidance"] = step["steering_guidance"]
                tree.stats["pending_steering_notes"] = 0
                tree.stats["steering_applied"] = int(tree.stats.get("steering_applied", 0)) + len(note_lines)
                await self._emit(
                    EventType.REASONING_OBSERVATION_RECEIVED,
                    {
                        "tree_id": tree.tree_id,
                        "session_id": tree.session_id,
                        "user_id": tree.user_id,
                        "node_id": node.node_id,
                        "kind": "steering",
                        "count": len(note_lines),
                    },
                )
        strategy_hints = (
            self.template_memory.get_strategy_hints(user_id=user_id)
            if self.template_memory
            else {}
        )
        merged_hints = dict(strategy_hints or {})
        extra_steps: List[Dict[str, Any]] = []

        try:
            if self._is_stop_requested(tree.tree_id):
                return []
            if step.get("requires_memory") and tree.stats["memory_calls"] < policy["max_memory_calls"]:
                memory_query = step.get("memory_query") or step.get("goal") or node.title
                memory_observation = await self._run_memory_lookup(
                    tree=tree,
                    node=node,
                    session_id=session_id,
                    user_id=user_id,
                    query=memory_query,
                    run_context=run_context,
                    user_config=user_config,
                )
                if memory_observation:
                    observations.append(f"Memory:\n{memory_observation}")

            react_rounds = max(1, int(policy["max_replan_rounds"]) + 1)
            for _ in range(react_rounds):
                if self._is_stop_requested(tree.tree_id):
                    break
                budget_ledger = self.budget_ledger.build(tree, policy)
                if self.budget_ledger.should_stop_reasoning(budget_ledger):
                    observations.append(
                        "Budget:\nReasoning budget exhausted; stop expanding this step and synthesize from current findings."
                    )
                    break
                tree.stats["react_rounds"] = int(tree.stats.get("react_rounds", 0) or 0) + 1
                budget_ledger = self.budget_ledger.build(tree, policy)
                decision = await self._replan_step(
                    tree=tree,
                    node=node,
                    user_message=user_message,
                    observations=observations,
                    budget_ledger=budget_ledger,
                    user_config=user_config,
                    user_id=user_id,
                )
                next_action = (decision.get("next_action") or "done").lower()
                extra_steps.extend(
                    item for item in decision.get("additional_steps", []) if isinstance(item, dict)
                )

                if next_action == "memory" and tree.stats["memory_calls"] < policy["max_memory_calls"]:
                    query = decision.get("memory_query") or node.title
                    memory_observation = await self._run_memory_lookup(
                        tree=tree,
                        node=node,
                        session_id=session_id,
                        user_id=user_id,
                        query=query,
                        run_context=run_context,
                        user_config=user_config,
                    )
                    if memory_observation:
                        observations.append(f"Memory:\n{memory_observation}")
                    continue

                if (
                    next_action == "tool"
                    and tree.stats["tool_calls"] < policy["max_tool_calls"]
                    and not self.budget_ledger.should_avoid_external_actions(budget_ledger)
                ):
                    self._transition_node_status(
                        tree=tree,
                        node=node,
                        target=WAITING_TOOL,
                        reason="awaiting_tool",
                        checkpoint={
                            "phase": "tool",
                            "tool_intent": decision.get("tool_intent") or step.get("tool_intent") or node.title,
                        },
                    )
                    tool_step = {
                        "goal": node.title,
                        "tool_intent": decision.get("tool_intent") or step.get("tool_intent") or node.title,
                        "requires_tools": True,
                    }
                    tool_observation = await self._run_tool_step(
                        tree=tree,
                        node=node,
                        session_id=session_id,
                        user_id=user_id,
                        step=tool_step,
                        user_message=user_message,
                        observations=observations,
                        user_config=user_config,
                        policy=policy,
                        run_context=run_context,
                    )
                    self._resume_node_from_waiting_tool(tree=tree, node=node)
                    if tool_observation:
                        observations.append(f"Tool:\n{tool_observation}")
                        if self._looks_like_failure_observation(tool_observation):
                            tree.stats["react_failed_observations"] = int(
                                tree.stats.get("react_failed_observations", 0) or 0
                            ) + 1
                    continue

                if next_action == "tool" and self.budget_ledger.should_avoid_external_actions(budget_ledger):
                    think_observation = await self._run_think_step(
                        tree=tree,
                        node=node,
                        user_message=user_message,
                        recent_messages=recent_messages,
                        observations=observations
                        + [
                            "Budget:\nExternal action budget is constrained by elapsed runtime, repeated low-yield tool failures, or global ReAct round usage. Synthesize from current findings instead of starting another external lookup."
                        ],
                        user_config=user_config,
                        user_id=user_id,
                    )
                    if think_observation:
                        observations.append(f"Think:\n{think_observation}")
                    break

                if next_action == "think":
                    think_observation = await self._run_think_step(
                        tree=tree,
                        node=node,
                        user_message=user_message,
                        recent_messages=recent_messages,
                        observations=observations,
                        user_config=user_config,
                        user_id=user_id,
                    )
                    if think_observation:
                        observations.append(f"Think:\n{think_observation}")
                    continue

                break

            if not self._is_stop_requested(tree.tree_id) and not observations:
                think_observation = await self._run_think_step(
                    tree=tree,
                    node=node,
                    user_message=user_message,
                    recent_messages=recent_messages,
                    observations=observations,
                    user_config=user_config,
                    user_id=user_id,
                )
                if think_observation:
                    observations.append(f"Think:\n{think_observation}")

            if (
                not self._is_stop_requested(tree.tree_id)
                and not extra_steps
                and observations
                and self._node_depth(tree, node_id) < policy["max_depth"]
                and not self.budget_ledger.should_avoid_external_actions(self.budget_ledger.build(tree, policy))
            ):
                expanded = await self._plan_steps(
                    tree=tree,
                    user_message=user_message,
                    recent_messages=recent_messages,
                    user_config=user_config,
                    user_id=user_id,
                    policy=policy,
                    strategy_hints=merged_hints,
                    max_candidates=policy["branch_factor"],
                    observation_context="\n\n".join(observations),
                )
                extra_steps.extend(expanded)

            final_observation = "\n\n".join(observations).strip()
            self._mark_node_succeeded(
                tree=tree,
                node=node,
                observation=final_observation,
                evidence=observations,
                result={
                    "generated_steps": len(extra_steps),
                    "snapshot": self._snapshot_node(node),
                },
            )
            await self._emit_node(tree, node, EventType.REASONING_NODE_COMPLETED)
            return extra_steps[: policy["branch_factor"]]
        except Exception as e:
            if node.status not in TERMINAL_STATES:
                try:
                    self._transition_node_status(
                        tree=tree,
                        node=node,
                        target=FAILED,
                        reason=f"execute_step_error:{e}",
                    )
                except Exception:
                    node.status = FAILED
                    node.updated_at = time.time()
            raise

    async def _select_beam_nodes(
        self,
        *,
        tree: ReasoningTree,
        candidate_node_ids: List[str],
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        policy: Dict[str, Any],
        stage: str,
    ) -> List[str]:
        if not candidate_node_ids:
            return []
        scored: List[tuple[str, float]] = []
        for node_id in candidate_node_ids:
            node = tree.nodes.get(node_id)
            if not node:
                continue
            score_data = await self._vote_branch_score(
                tree=tree,
                node=node,
                user_message=user_message,
                user_config=user_config,
                user_id=user_id,
                policy=policy,
                stage=stage,
            )
            score = float(score_data.get("score", 0.0))
            node.metadata["beam_score"] = score
            node.metadata["beam_votes"] = score_data.get("votes", [])
            node.metadata["beam_stage"] = stage
            if score >= policy["min_branch_score"]:
                scored.append((node_id, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        top = scored[: policy["beam_width"]]
        return [node_id for node_id, _ in top]

    async def _vote_branch_score(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        policy: Dict[str, Any],
        stage: str,
    ) -> Dict[str, Any]:
        votes: List[float] = []
        rationales: List[str] = []
        for _ in range(policy["candidate_votes"]):
            vote = await self._score_branch_once(
                tree=tree,
                node=node,
                user_message=user_message,
                user_config=user_config,
                user_id=user_id,
                stage=stage,
            )
            votes.append(float(vote.get("score", 0.0)))
            rationale = str(vote.get("rationale", "")).strip()
            if rationale:
                rationales.append(rationale)
        avg = sum(votes) / max(1, len(votes))
        return {
            "score": avg,
            "votes": votes,
            "rationale": rationales[:3],
        }

    async def _score_branch_once(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        stage: str,
    ) -> Dict[str, Any]:
        prompt = (
            "Score a candidate reasoning branch for relevance and expected utility.\n"
            "Return strict JSON: {\"score\": number, \"rationale\": string}.\n"
            "score range is 0.0 to 1.0. Higher is better."
        )
        strategy_hints = (
            self.template_memory.get_strategy_hints(user_id=user_id)
            if (self.template_memory and user_id)
            else {}
        )
        payload = {
            "stage": stage,
            "task": user_message,
            "strategy_hints": strategy_hints,
            "candidate": {
                "title": node.title,
                "kind": node.kind,
                "metadata": node.metadata,
                "observation": self._truncate_text(node.observation or node.summary or "", 1200),
            },
            "tree_stats": tree.stats,
        }
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"score": 0.0, "rationale": "invalid scorer output"}
        try:
            score = float(result.get("score", 0.0))
        except Exception:
            score = 0.0
        score = min(1.0, max(0.0, score))
        return {"score": score, "rationale": str(result.get("rationale", ""))}

    async def _run_memory_lookup(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        session_id: str,
        user_id: str,
        query: str,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not self.memory_service or not self.memory_service.is_enabled():
            return ""
        context_fields = self._extract_run_context_fields(
            run_context,
            session_id=session_id,
            user_id=user_id,
        )
        child = self._add_node(
            tree,
            parent_id=node.node_id,
            kind="memory",
            title=f"memory: {query}",
            metadata={"query": query},
        )
        self._transition_node_status(
            tree=tree,
            node=child,
            target=RUNNING,
            reason="memory_lookup_started",
        )
        await self._emit(
            EventType.REASONING_MEMORY_REQUESTED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "query": query,
                **context_fields,
            },
        )
        try:
            result = await self.memory_service.get_context(
                query=query,
                session_id=session_id,
                user_id=user_id,
                run_context=run_context,
            )
        except Exception as e:
            result = f"[memory error] {e}"
        self._mark_node_succeeded(
            tree=tree,
            node=child,
            observation=result or "",
            evidence=[result or ""],
            result={"query": query},
        )
        tree.stats["memory_calls"] += 1
        await self._emit(
            EventType.REASONING_OBSERVATION_RECEIVED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "kind": "memory",
                **context_fields,
            },
        )
        return child.observation

    async def _start_workflow_tool_trace(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        session_id: str,
        user_id: str,
        tool_type: str,
        service_name: str,
        tool_name: str,
        args: Dict[str, Any],
        intent: str,
        policy: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not self.workflow_engine:
            return None
        if not self._to_bool((policy or {}).get("workflow_tool_bridge"), default=True):
            return None
        try:
            from .workflow_models import WorkflowDefinition, WorkflowStep

            workflow_id = f"react_tool_{tree.tree_id}_{node.node_id}"
            definition = WorkflowDefinition(
                workflow_id=workflow_id,
                workflow_type="linear",
                name=f"ReAct Tool {service_name}.{tool_name}",
                description="Ephemeral workflow trace for a ReAct tool action.",
                owner_user_id=user_id,
                steps=[
                    WorkflowStep(
                        step_id="tool_action",
                        step_type="tool_step",
                        name=f"{service_name}.{tool_name}",
                        description=intent or node.title,
                        inputs={
                            "tool_type": tool_type,
                            "service_name": service_name,
                            "tool_name": tool_name,
                            "args": dict(args or {}),
                            "tree_id": tree.tree_id,
                            "node_id": node.node_id,
                        },
                    )
                ],
                policy={
                    "source": "reasoning_react",
                    "tree_id": tree.tree_id,
                    "node_id": node.node_id,
                },
            )
            self.workflow_engine.define_workflow(definition)
            start_async = getattr(self.workflow_engine, "start_workflow_async", None)
            kwargs = {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "user_id": user_id,
                "workspace_id": session_id,
                "run_metadata": {
                    "source": "reasoning_react",
                    "tree_id": tree.tree_id,
                    "node_id": node.node_id,
                    "tool_type": tool_type,
                    "service_name": service_name,
                    "tool_name": tool_name,
                    "args": dict(args or {}),
                },
            }
            if callable(start_async):
                run = await start_async(**kwargs)
            else:
                run = self.workflow_engine.start_workflow(**kwargs)
            return str(getattr(run, "workflow_run_id", "") or "").strip() or None
        except Exception as e:
            logger.debug("ReasoningService: workflow tool trace skipped: {}", e)
            return None

    def _append_workflow_tool_observation(
        self,
        *,
        workflow_run_id: Optional[str],
        tool_type: str,
        service_name: str,
        tool_name: str,
        args: Dict[str, Any],
        observation: str,
        verify: Dict[str, Any],
    ) -> None:
        if not self.workflow_engine or not workflow_run_id:
            return
        try:
            append_method = getattr(self.workflow_engine, "append_run_observation", None)
            payload = {
                "kind": "tool",
                "tool_type": tool_type,
                "service_name": service_name,
                "tool_name": tool_name,
                "args": dict(args or {}),
                "observation": observation,
                "verification": dict(verify or {}),
                "at": time.time(),
            }
            if callable(append_method):
                append_method(workflow_run_id, payload)
                return
            run = self.workflow_engine.get_run(workflow_run_id)
            if not run:
                return
            observations = run.run_metadata.setdefault("observations", [])
            if isinstance(observations, list):
                observations.append(payload)
                run.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.debug("ReasoningService: append workflow observation skipped: {}", e)

    async def _run_tool_step(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        session_id: str,
        user_id: str,
        step: Dict[str, Any],
        user_message: str,
        observations: List[str],
        user_config: Optional[Dict[str, Any]],
        policy: Optional[Dict[str, Any]] = None,
        run_context: Optional[Any] = None,
    ) -> str:
        if not self.tool_service:
            return ""
        context_fields = self._extract_run_context_fields(
            run_context,
            session_id=session_id,
            user_id=user_id,
        )
        catalog = await self.tool_service.get_tool_catalog()
        if not catalog:
            return ""
        replay_failure_observation = ""
        replay_selected = await self._select_replay_tool(
            user_id=user_id,
            user_message=user_message,
            step=step,
            catalog=catalog,
            user_config=user_config,
        )
        if replay_selected.get("use_tool"):
            replay_payload = await self._execute_selected_tool(
                tree=tree,
                node=node,
                session_id=session_id,
                user_id=user_id,
                selected=replay_selected,
                step=step,
                context_fields=context_fields,
                user_config=user_config,
                run_context=run_context,
                policy=policy,
            )
            if replay_payload.get("ok"):
                return str(replay_payload.get("observation", "") or "")
            replay_failure_observation = str(replay_payload.get("observation", "") or "").strip()

        selected = await self._select_tool(
            step=step,
            user_message=user_message,
            observations=observations,
            catalog=catalog,
            user_config=user_config,
            user_id=user_id,
        )
        if not selected.get("use_tool"):
            return replay_failure_observation

        selected_payload = await self._execute_selected_tool(
            tree=tree,
            node=node,
            session_id=session_id,
            user_id=user_id,
            selected=selected,
            step=step,
            context_fields=context_fields,
            user_config=user_config,
            run_context=run_context,
            policy=policy,
        )
        selected_observation = str(selected_payload.get("observation", "") or "").strip()
        if selected_payload.get("ok"):
            return selected_observation
        if replay_failure_observation:
            if selected_observation:
                return f"{replay_failure_observation}\n\n{selected_observation}".strip()
            return replay_failure_observation
        return selected_observation

    async def _select_replay_tool(
        self,
        *,
        user_id: str,
        user_message: str,
        step: Dict[str, Any],
        catalog: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.template_memory:
            return {"use_tool": False}
        try:
            matched = self.template_memory.match_action_template(
                user_id=user_id,
                task=user_message,
                tool_intent=str(step.get("tool_intent") or step.get("goal") or "").strip(),
            )
        except Exception:
            return {"use_tool": False}
        actions = matched.get("actions", []) if isinstance(matched, dict) else []
        mind_graph = matched.get("mind_graph") if isinstance(matched, dict) else None
        if not isinstance(actions, list) or not actions:
            return {"use_tool": False}
        action = actions[0] if isinstance(actions[0], dict) else {}
        if isinstance(mind_graph, dict) and mind_graph:
            llm_compiled = await self._llm_compile_replay_tool(
                user_message=user_message,
                step=step,
                mind_graph=mind_graph,
                catalog=catalog,
                user_config=user_config,
                user_id=user_id,
                fallback_args=action.get("args") if isinstance(action.get("args"), dict) else {},
            )
            normalized_llm = self._normalize_selected_tool(llm_compiled, catalog)
            if normalized_llm.get("use_tool"):
                normalized_llm["why"] = "template_mind_graph_llm_compile"
                return normalized_llm
        replay_step = {
            "title": "replay action by intent",
            "goal": str(action.get("action_intent") or step.get("goal") or "").strip(),
            "tool_intent": (
                f"{str(action.get('action_intent') or '').strip()} "
                f"{str(action.get('capability') or '').strip()} "
                f"{str(step.get('tool_intent') or '').strip()}"
            ).strip(),
            "requires_tools": True,
        }
        strategy_pick = self.tool_strategy.recommend(
            step=replay_step,
            user_message=user_message,
            observations=[],
            catalog=catalog,
            strategy_hints={},
        )
        normalized_strategy = self._normalize_selected_tool(
            strategy_pick if isinstance(strategy_pick, dict) else {},
            catalog,
        )
        if normalized_strategy.get("use_tool"):
            merged_args = action.get("args") if isinstance(action.get("args"), dict) else {}
            strategy_args = normalized_strategy.get("args") if isinstance(normalized_strategy.get("args"), dict) else {}
            normalized_strategy["args"] = strategy_args if strategy_args else merged_args
            normalized_strategy["why"] = "template_semantic_replay"
            return normalized_strategy

        selected = {
            "use_tool": True,
            "tool_type": "mcp",
            "service_name": str(action.get("service_name", "")).strip(),
            "tool_name": str(action.get("tool_name", "")).strip(),
            "args": action.get("args") if isinstance(action.get("args"), dict) else {},
            "why": "template_exact_replay",
        }
        normalized = self._normalize_selected_tool(selected, catalog)
        if normalized.get("use_tool"):
            return normalized
        return {"use_tool": False}

    async def _llm_compile_replay_tool(
        self,
        *,
        user_message: str,
        step: Dict[str, Any],
        mind_graph: Dict[str, Any],
        catalog: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        fallback_args: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt = (
            "Compile one executable tool call for the current step from an execution mind graph.\n"
            "Prefer capability/intent alignment over historical exact tool binding.\n"
            "Return strict JSON: "
            "{\"use_tool\":bool,\"tool_type\":string,\"service_name\":string,\"tool_name\":string,"
            "\"args\":object,\"why\":string}."
        )
        catalog_rows = [
            {
                "tool_type": str(item.get("tool_type", "mcp")),
                "service_name": str(item.get("service_name", "") or ""),
                "tool_name": str(item.get("tool_name", "") or ""),
                "description": str(item.get("description", "") or ""),
            }
            for item in (catalog or [])[:40]
            if isinstance(item, dict)
        ]
        payload = {
            "task": user_message,
            "current_step": {
                "title": str(step.get("title", "") or ""),
                "goal": str(step.get("goal", "") or ""),
                "tool_intent": str(step.get("tool_intent", "") or ""),
            },
            "mind_graph": {
                "goal": str(mind_graph.get("goal", "") or ""),
                "nodes": mind_graph.get("nodes", [])[:12] if isinstance(mind_graph.get("nodes"), list) else [],
                "edges": mind_graph.get("edges", [])[:18] if isinstance(mind_graph.get("edges"), list) else [],
            },
            "available_tools": catalog_rows,
            "fallback_args": dict(fallback_args or {}),
        }
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            user_config=user_config,
            user_id=user_id,
        )
        return result if isinstance(result, dict) else {"use_tool": False}

    async def _execute_selected_tool(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        session_id: str,
        user_id: str,
        selected: Dict[str, Any],
        step: Dict[str, Any],
        context_fields: Dict[str, Any],
        user_config: Optional[Dict[str, Any]],
        run_context: Optional[Any],
        policy: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tool_type = selected.get("tool_type") or "mcp"
        service_name = selected.get("service_name") or selected.get("tool_name")
        tool_name = selected.get("tool_name") or service_name
        args = selected.get("args") or {}
        workflow_run_id = await self._start_workflow_tool_trace(
            tree=tree,
            node=node,
            session_id=session_id,
            user_id=user_id,
            tool_type=tool_type,
            service_name=service_name,
            tool_name=tool_name,
            args=args,
            intent=str(step.get("tool_intent") or step.get("goal") or node.title),
            policy=policy,
        )
        child = self._add_node(
            tree,
            parent_id=node.node_id,
            kind="tool",
            title=f"tool: {service_name}.{tool_name}",
            metadata={
                "tool_type": tool_type,
                "service_name": service_name,
                "tool_name": tool_name,
                "args": args,
                "workflow_run_id": workflow_run_id,
            },
        )
        self._transition_node_status(
            tree=tree,
            node=child,
            target=RUNNING,
            reason="tool_execution_started",
            checkpoint={
                "phase": "tool_call",
                "service_name": service_name,
                "tool_name": tool_name,
            },
        )
        await self._emit(
            EventType.REASONING_TOOL_REQUESTED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "tool_type": tool_type,
                "service_name": service_name,
                "tool_name": tool_name,
                **context_fields,
            },
        )
        ctx_metadata = {"tree_id": tree.tree_id, "node_id": child.node_id}
        trace_id = context_fields.get("trace_id")
        if trace_id:
            ctx_metadata["trace_id"] = trace_id
        ctx = ToolInvocationContext(
            session_id=session_id,
            user_id=user_id,
            source="reasoning",
            metadata=ctx_metadata,
        )

        tool_call_started = time.time()
        try:
            use_workflow_bridge = bool(workflow_run_id) and bool(
                self.workflow_engine and hasattr(self.workflow_engine, "run_tool_action")
            )
            if use_workflow_bridge:
                wf_payload = await self.workflow_engine.run_tool_action(
                    workflow_run_id=workflow_run_id,
                    session_id=session_id,
                    user_id=user_id,
                    tool_type=tool_type,
                    service_name=service_name,
                    tool_name=tool_name,
                    args=args,
                    run_context=run_context,
                    user_config=user_config,
                    metadata={
                        "tree_id": tree.tree_id,
                        "node_id": child.node_id,
                        "trace_id": trace_id,
                        "source": "reasoning_react",
                    },
                )
                result = wf_payload.get("result")
            else:
                result = await self.tool_service.call_tool(
                    tool_name=tool_name,
                    params={
                        "agentType": tool_type,
                        "service_name": service_name,
                        "tool_name": tool_name,
                        **args,
                    },
                    ctx=ctx,
                    request_id=f"reasoning_{tree.tree_id}",
                    run_context=run_context,
                    user_config=user_config,
                )
        except Exception as e:
            result = f"[tool error] {e}"

        result_text = self._stringify_observation(result)
        verify = await self._verify_tool_observation(
            step=step,
            observation=result_text,
            user_config=user_config,
            user_id=user_id,
        )
        self._append_workflow_tool_observation(
            workflow_run_id=workflow_run_id,
            tool_type=tool_type,
            service_name=service_name,
            tool_name=tool_name,
            args=args,
            observation=result_text,
            verify=verify,
        )
        child.verifier_state = dict(verify or {})
        child.tool_calls.append(
            {
                "tool_type": tool_type,
                "service_name": service_name,
                "tool_name": tool_name,
                "args": args,
                "at": time.time(),
            }
        )

        tree.stats["tool_calls"] += 1
        tree.stats["tool_failures"] = int(tree.stats.get("tool_failures", 0))
        verify_ok = bool(verify.get("ok", True))
        if verify_ok:
            self._tool_selection_stats["tool_observation_ok"] += 1
        else:
            self._tool_selection_stats["tool_observation_failed"] += 1
            tree.stats["tool_failures"] += 1

        self._record_tool_quality(
            service_name=service_name,
            tool_name=tool_name,
            ok=verify_ok,
            latency_ms=(time.time() - tool_call_started) * 1000.0,
        )

        if verify_ok:
            self._mark_node_succeeded(
                tree=tree,
                node=child,
                observation=result_text,
                evidence=[result_text],
                result={"verification": verify},
            )
        else:
            conf = float(verify.get("confidence", 0.0) or 0.0)
            if conf < 0.9:
                self._transition_node_status(
                    tree=tree,
                    node=child,
                    target=WAITING_HUMAN,
                    reason="tool_verification_uncertain",
                    checkpoint={"phase": "human_review", "verification": verify},
                )
                child.human_gate = {
                    "question": "Should this tool observation still be accepted?",
                    "verification": verify,
                }
                self._resume_node_from_waiting_human(tree=tree, node=child, approved=False)
            else:
                self._transition_node_status(
                    tree=tree,
                    node=child,
                    target=FAILED,
                    reason="tool_verification_failed",
                )
            child.observation = result_text
            child.summary = result_text

        await self._emit(
            EventType.REASONING_OBSERVATION_RECEIVED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "kind": "tool",
                **context_fields,
            },
        )

        if verify_ok:
            return {"ok": True, "observation": child.observation}
        reason = str(verify.get("reason", "") or "").strip()
        return {
            "ok": False,
            "observation": f"[tool verification failed] {reason}\n{child.observation}",
            "reason": reason,
        }

    async def _select_tool(
        self,
        *,
        step: Dict[str, Any],
        user_message: str,
        observations: List[str],
        catalog: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        strategy_hints = (
            self.template_memory.get_strategy_hints(user_id=user_id)
            if (self.template_memory and user_id)
            else {}
        )
        merged_hints = dict(strategy_hints or {})
        runtime_quality = self._runtime_tool_quality_hints(limit=20)
        if runtime_quality:
            merged_hints["tool_quality"] = runtime_quality
        strategy_pick = self.tool_strategy.recommend(
            step=step,
            user_message=user_message,
            observations=observations,
            catalog=catalog,
            strategy_hints=merged_hints,
        )
        candidates = strategy_pick.get("candidates", []) if isinstance(strategy_pick, dict) else []
        candidates_text = "\n".join(
            f"- score={item.get('score', 0):.2f} type={item.get('tool_type', 'unknown')} "
            f"service={item.get('service_name', '')} tool={item.get('tool_name', '')} "
            f"reasons={item.get('reasons', [])}"
            for item in candidates[:8]
        )
        catalog_text = "\n".join(
            f"- type={item.get('tool_type', 'unknown')} service={item['service_name']} "
            f"tool={item['tool_name']} desc={item.get('description', '')}"
            for item in catalog[:40]
        )
        prompt = (
            "Choose at most one tool for the current reasoning step. Return strict JSON: "
            "{\"use_tool\":bool,\"tool_type\":string,\"service_name\":string,\"tool_name\":string,"
            "\"args\":object,\"why\":string}. If uncertain, set use_tool=false."
        )
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Overall task:\n{user_message}\n\n"
                        f"Current step:\n{json.dumps(step, ensure_ascii=False)}\n\n"
                        f"Historical tool hints:\n{json.dumps(strategy_hints.get('preferred_tools', []), ensure_ascii=False)}\n\n"
                        f"Current observations:\n{self._truncate_text(chr(10).join(observations), 2000)}\n\n"
                        f"Strategy engine candidates:\n{candidates_text or '(none)'}\n\n"
                        f"Available tools:\n{catalog_text}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            result = {}

        result["use_tool"] = self._to_bool(result.get("use_tool"), default=False)
        if result["use_tool"]:
            if not result.get("service_name") or not result.get("tool_name"):
                preferred = (strategy_hints.get("preferred_tools", []) or [{}])[0]
                if isinstance(preferred, dict):
                    result["service_name"] = result.get("service_name") or preferred.get("service_name")
                    result["tool_name"] = result.get("tool_name") or preferred.get("tool_name")
            if (not result.get("service_name") or not result.get("tool_name")) and candidates:
                top_candidate = candidates[0] if isinstance(candidates[0], dict) else {}
                result["service_name"] = result.get("service_name") or top_candidate.get("service_name")
                result["tool_name"] = result.get("tool_name") or top_candidate.get("tool_name")

        self._tool_selection_stats["total"] += 1
        chosen = self._normalize_selected_tool(result, catalog)
        if chosen.get("use_tool"):
            self._tool_selection_stats["llm_selected"] += 1
            return chosen

        # LLM gave invalid/no pick: fallback to deterministic strategy candidate.
        fallback = self._normalize_selected_tool(strategy_pick if isinstance(strategy_pick, dict) else {}, catalog)
        if fallback.get("use_tool"):
            self._tool_selection_stats["strategy_fallback"] += 1
            return fallback

        self._tool_selection_stats["no_tool"] += 1
        return {"use_tool": False}

    async def _verify_tool_observation(
        self,
        *,
        step: Dict[str, Any],
        observation: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Lightweight post-tool verifier to support auto-replan decisions.
        """
        text = (observation or "").strip()
        lowered = text.lower()
        if not text:
            return {"ok": False, "confidence": 0.9, "reason": "empty_observation"}
        bad_markers = (
            "[tool error]",
            "error:",
            "traceback",
            "exception",
            "permission denied",
            "sandbox blocked",
            "timed out",
        )
        if any(m in lowered for m in bad_markers):
            return {"ok": False, "confidence": 0.95, "reason": "tool_error_marker"}
        if lowered.startswith("error") or lowered.startswith("failed"):
            return {"ok": False, "confidence": 0.8, "reason": "negative_prefix"}

        prompt = (
            "You verify whether a tool observation indicates successful progress for a reasoning step.\n"
            "Return strict JSON: {\"ok\":bool,\"confidence\":0..1,\"reason\":string}."
        )
        payload = {
            "step": {
                "title": str(step.get("title", "") or ""),
                "goal": str(step.get("goal", "") or ""),
                "tool_intent": str(step.get("tool_intent", "") or ""),
            },
            "observation": self._truncate_text(text, 1600),
        }
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"ok": True, "confidence": 0.5, "reason": "verifier_unavailable"}
        ok = self._to_bool(result.get("ok"), default=True)
        try:
            conf = float(result.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        conf = min(1.0, max(0.0, conf))
        return {
            "ok": ok,
            "confidence": conf,
            "reason": str(result.get("reason", "") or ""),
        }
    def _record_tool_quality(
        self,
        *,
        service_name: str,
        tool_name: str,
        ok: bool,
        latency_ms: float,
    ) -> None:
        self.tool_quality.record(
            service_name=service_name,
            tool_name=tool_name,
            ok=ok,
            latency_ms=latency_ms,
        )

    def _runtime_tool_quality_hints(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        return self.tool_quality.hints(limit=limit)

    def _normalize_selected_tool(
        self,
        selected: Dict[str, Any],
        catalog: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self.tool_catalog.normalize_selected_tool(selected, catalog)

    @staticmethod
    def _resolve_catalog_entry(
        catalog: List[Dict[str, Any]],
        service_name: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        return ReasoningToolCatalogResolver().resolve_catalog_entry(catalog, service_name, tool_name)

    @staticmethod
    def _normalize_tool_id(value: str) -> str:
        return ReasoningToolCatalogResolver.normalize_tool_id(value)

    @staticmethod
    def _find_catalog_entry(
        catalog: List[Dict[str, Any]],
        service_name: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        return ReasoningToolCatalogResolver.find_catalog_entry(catalog, service_name, tool_name)

    async def _run_think_step(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        observations: List[str],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> str:
        child = self._add_node(
            tree,
            parent_id=node.node_id,
            kind="think",
            title=f"think: {node.title}",
        )
        prompt = (
            "Think explicitly for the current reasoning step and produce a compact working note. "
            "Do not answer the user yet. Focus on what is known, what matters, and the next useful conclusion."
        )
        response = await self._call_text(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{user_message}\n\n"
                        f"Current step:\n{node.title}\n\n"
                        f"Recent context:\n{self._format_recent_messages(recent_messages)}\n\n"
                        f"Observations:\n{self._truncate_text(chr(10).join(observations), 2500)}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        self._transition_node_status(
            tree=tree,
            node=child,
            target=RUNNING,
            reason="think_step_started",
        )
        self._mark_node_succeeded(
            tree=tree,
            node=child,
            observation=response,
            evidence=[response],
            result={"kind": "think"},
        )
        tree.stats["think_calls"] += 1
        await self._emit(
            EventType.REASONING_OBSERVATION_RECEIVED,
            {
                "tree_id": tree.tree_id,
                "session_id": tree.session_id,
                "user_id": tree.user_id,
                "node_id": child.node_id,
                "kind": "think",
            },
        )
        return response

    async def _replan_step(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        user_message: str,
        observations: List[str],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
        budget_ledger: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ledger = budget_ledger or self.budget_ledger.build(tree, {})
        prompt = (
            "Review the current reasoning step and decide the next action. "
            "Use lightweight strategy reflection before choosing: decide whether another tool call is likely to add useful evidence, "
            "whether recent failures indicate a source/tool/channel limitation, whether a think step can synthesize enough from current findings, "
            "or whether the step is already done. Avoid blind tool retries; choose tool only when the next external action has a clear marginal value. "
            "Respect the global budget ledger. If runtime is over target, ReAct rounds are near/exhausted, or tools are low-yield, prefer think/done and synthesize with uncertainty instead of starting more external lookups. "
            "Choose think when the useful move is synthesis, reframing, or extracting a conclusion from partial observations. "
            "Choose done when current findings are sufficient for this step or further action would mostly repeat failed paths. "
            "Return strict JSON: "
            "{\"next_action\":\"done|memory|tool|think\",\"memory_query\":string,"
            "\"tool_intent\":string,\"additional_steps\":[{\"title\":string,\"goal\":string,"
            "\"requires_memory\":bool,\"memory_query\":string,\"requires_tools\":bool,"
            "\"tool_intent\":string,\"notes\":string}],\"strategy_reflection\":string}"
        )
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{user_message}\n\n"
                        f"Current step:\n{node.title}\n\n"
                        f"Global budget ledger:\n{json.dumps(ledger, ensure_ascii=False)}\n\n"
                        f"Current findings:\n{self._truncate_text(chr(10).join(observations), 3000)}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        await self._emit(
            EventType.REASONING_REPLAN,
            {
                "tree_id": tree.tree_id,
                "session_id": tree.session_id,
                "user_id": tree.user_id,
                "node_id": node.node_id,
                "decision": result or {},
            },
        )
        return result if isinstance(result, dict) else {"next_action": "done"}

    async def _summarize_tree(
        self,
        *,
        tree: ReasoningTree,
        user_message: str,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> str:
        traces: List[str] = []
        for node in tree.nodes.values():
            if node.kind in {"plan", "thought"} and node.summary:
                traces.append(f"[{node.title}]\n{node.summary}")
        if not traces:
            return ""
        prompt = (
            "Summarize the reasoning results into internal context for the final assistant answer. "
            "Return plain text only. Preserve enough substance for a high-quality user-facing synthesis: "
            "core conclusion, strongest supporting points, relevant memory/tool findings, failed or blocked evidence paths, "
            "uncertainty limits, tradeoffs, and practical recommendations. Do not expose hidden chain-of-thought or runtime protocol details."
        )
        return await self._call_text(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Original task:\n{user_message}\n\n"
                        f"Reasoning trace:\n{self._truncate_text(chr(10).join(traces), 5000)}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )

    async def _call_json(
        self,
        messages: List[Dict[str, str]],
        *,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        text = await self._call_text(messages, user_config=user_config, user_id=user_id)
        return self._extract_json(text)

    async def _judge_task_success(
        self,
        *,
        user_message: str,
        assistant_output: str,
        gate: Dict[str, Any],
        policy: Dict[str, Any],
        tree_stats: Dict[str, Any],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        prompt = (
            "You evaluate whether an assistant response successfully completed the user's task.\n"
            "Return strict JSON: {\"outcome\":\"success|failure|unsure\",\"confidence\":0..1,\"reason\":string}.\n"
            "Choose 'unsure' if information is insufficient."
        )
        payload = {
            "user_task": user_message,
            "assistant_output": self._truncate_text(assistant_output or "", 3000),
            "gate": gate,
            "reasoning_policy": {
                "max_depth": policy.get("max_depth"),
                "max_nodes": policy.get("max_nodes"),
                "max_iterations": policy.get("max_iterations"),
                "max_memory_calls": policy.get("max_memory_calls"),
                "max_tool_calls": policy.get("max_tool_calls"),
            },
            "tree_stats": tree_stats,
        }
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"outcome": "unsure", "confidence": 0.0, "reason": "invalid_judge_output"}
        outcome = str(result.get("outcome", "unsure") or "unsure").strip().lower()
        if outcome not in {"success", "failure", "unsure"}:
            outcome = "unsure"
        try:
            confidence = float(result.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        return {
            "outcome": outcome,
            "confidence": confidence,
            "reason": str(result.get("reason", "") or ""),
        }

    @staticmethod
    def _looks_like_failure_observation(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        markers = (
            "[tool verification failed]",
            "[tool error]",
            "[memory error]",
            "error:",
            "failed:",
            "call failed",
            "timeout",
            "rate limit",
        )
        return any(marker in lowered for marker in markers)

    def _collect_observation_samples(
        self,
        *,
        tree: ReasoningTree,
        limit: int = 5,
    ) -> Dict[str, List[str]]:
        failed: List[str] = []
        succeeded: List[str] = []
        for node in tree.nodes.values():
            obs = str(node.observation or node.summary or "").strip()
            if not obs:
                continue
            if self._looks_like_failure_observation(obs):
                if len(failed) < max(1, int(limit)):
                    failed.append(self._truncate_text(obs, 500))
            elif len(succeeded) < max(1, int(limit)):
                succeeded.append(self._truncate_text(obs, 500))
        return {"failed": failed, "succeeded": succeeded}

    async def _judge_runtime_feasibility(
        self,
        *,
        user_message: str,
        tree: ReasoningTree,
        policy: Dict[str, Any],
        iteration_budget: int,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        samples = self._collect_observation_samples(tree=tree, limit=6)
        prompt = (
            "You are a runtime evaluator for an autonomous reasoning loop.\n"
            "Decide whether the task should finish as success or fail as currently infeasible.\n"
            "Failure means: despite retries/replanning, constraints or repeated errors block completion now.\n"
            "Return strict JSON: "
            "{\"outcome\":\"success|failure|unsure\",\"confidence\":0..1,\"reason\":string,\"suggestion\":string}."
        )
        payload = {
            "user_task": user_message,
            "tree_stats": dict(tree.stats or {}),
            "iteration_budget": int(iteration_budget),
            "policy": {
                "max_iterations": policy.get("max_iterations"),
                "max_tool_calls": policy.get("max_tool_calls"),
                "max_replan_rounds": policy.get("max_replan_rounds"),
                "failure_confidence_threshold": policy.get("failure_confidence_threshold"),
            },
            "failed_observations": samples.get("failed", []),
            "successful_observations": samples.get("succeeded", []),
        }
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {
                "outcome": "unsure",
                "confidence": 0.0,
                "reason": "invalid_runtime_judge_output",
                "suggestion": "",
            }
        outcome = str(result.get("outcome", "unsure") or "unsure").strip().lower()
        if outcome not in {"success", "failure", "unsure"}:
            outcome = "unsure"
        try:
            confidence = float(result.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        return {
            "outcome": outcome,
            "confidence": confidence,
            "reason": str(result.get("reason", "") or ""),
            "suggestion": str(result.get("suggestion", "") or ""),
        }

    async def _decide_runtime_outcome(
        self,
        *,
        user_message: str,
        tree: ReasoningTree,
        policy: Dict[str, Any],
        iteration_budget: int,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        stats = dict(tree.stats or {})
        tool_calls = int(stats.get("tool_calls", 0) or 0)
        tool_failures = int(stats.get("tool_failures", 0) or 0)
        iterations = int(stats.get("iterations", 0) or 0)
        failure_threshold = float(policy.get("failure_confidence_threshold", 0.55) or 0.55)
        failed_node_count = sum(1 for node in tree.nodes.values() if str(node.status) == FAILED)
        successful_obs = self._collect_observation_samples(tree=tree, limit=2).get("succeeded", [])

        hard_block = tool_calls >= 2 and tool_failures >= tool_calls
        exhausted = iterations >= max(1, int(iteration_budget)) and tool_failures > 0
        repeated_fail = tool_failures >= max(2, min(4, int(policy.get("max_tool_calls", 0) or 0)))

        if not (hard_block or exhausted or repeated_fail):
            return {"status": "success", "reason": "runtime_progress_or_no_hard_block", "confidence": 1.0}

        judge = await self._judge_runtime_feasibility(
            user_message=user_message,
            tree=tree,
            policy=policy,
            iteration_budget=iteration_budget,
            user_config=user_config,
            user_id=user_id,
        )
        outcome = str(judge.get("outcome", "unsure") or "unsure").strip().lower()
        confidence = float(judge.get("confidence", 0.0) or 0.0)
        reason = str(judge.get("reason", "") or "")
        suggestion = str(judge.get("suggestion", "") or "")

        if outcome == "failure" and confidence >= failure_threshold:
            return {
                "status": "failed",
                "reason": reason or "llm_runtime_judge_failure",
                "confidence": confidence,
                "suggestion": suggestion,
            }
        if outcome == "success":
            return {
                "status": "success",
                "reason": reason or "llm_runtime_judge_success",
                "confidence": confidence,
                "suggestion": suggestion,
            }
        if hard_block and not successful_obs and failed_node_count > 0:
            return {
                "status": "failed",
                "reason": reason or "heuristic_hard_block_without_progress",
                "confidence": max(confidence, 0.6),
                "suggestion": suggestion,
            }
        return {
            "status": "success",
            "reason": reason or "runtime_judge_unsure_default_continue",
            "confidence": confidence,
            "suggestion": suggestion,
        }

    async def _call_text(
        self,
        messages: List[Dict[str, str]],
        *,
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> str:
        try:
            response = await self.conversation_core.call_llm(
                messages,
                user_config=user_config,
                user_id=user_id,
            )
        except TypeError:
            response = await self.conversation_core.call_llm(
                messages,
                user_config=user_config,
            )
        return (response or {}).get("content", "") or ""

    def _extract_json(self, text: str) -> Dict[str, Any]:
        return extract_json_object(text)

    def _format_recent_messages(self, messages: List[Dict[str, Any]]) -> str:
        return format_recent_messages(messages, keep_last=6, content_limit=300)

    def _truncate_text(self, text: str, limit: int) -> str:
        return truncate_text(text, limit)

    def _stringify_observation(self, value: Any) -> str:
        return stringify_observation(value)

    @staticmethod
    def _to_bool(value: Any, *, default: bool = False) -> bool:
        return to_bool(value, default=default)

    def _merge_steps(
        self,
        template_steps: List[Dict[str, Any]],
        generated_steps: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        return merge_steps(template_steps, generated_steps, limit)

    async def _export_plan_to_moirai(
        self,
        *,
        tree: ReasoningTree,
        session_id: str,
        user_id: str,
        user_message: str,
        steps: List[Dict[str, Any]],
        gate: Dict[str, Any],
        policy: Dict[str, Any],
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not policy.get("moirai_export_plan"):
            return None
        if not self.tool_service:
            return None

        moirai_steps = self._map_plan_steps_to_moirai(steps)
        if not moirai_steps:
            return None

        flow_name = f"reasoning-{tree.tree_id[:8]}"
        context_fields = self._extract_run_context_fields(
            run_context,
            session_id=session_id,
            user_id=user_id,
        )
        ctx_metadata = {"tree_id": tree.tree_id, "purpose": "plan_export"}
        trace_id = context_fields.get("trace_id")
        if trace_id:
            ctx_metadata["trace_id"] = trace_id
        ctx = ToolInvocationContext(
            session_id=session_id,
            user_id=user_id,
            source="reasoning",
            metadata=ctx_metadata,
        )
        args = {
            "agentType": "mcp",
            "service_name": "moirai",
            "tool_name": "create_flow",
            "name": flow_name,
            "goal": user_message,
            "steps": moirai_steps,
            "auto_start": bool(policy.get("moirai_auto_start", False)),
            "metadata": {
                "source": "reasoning_service",
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "gate": {
                    "needs_reasoning": bool(gate.get("needs_reasoning", False)),
                    "needs_memory": bool(gate.get("needs_memory", False)),
                    "needs_tools": bool(gate.get("needs_tools", False)),
                    "complexity": str(gate.get("complexity", "")),
                },
            },
        }

        try:
            result = await self.tool_service.call_tool(
                tool_name="create_flow",
                params=args,
                ctx=ctx,
                request_id=f"reasoning_moirai_{tree.tree_id}",
                run_context=run_context,
                user_config=user_config,
            )
        except Exception as e:
            logger.debug("ReasoningService: moirai export skipped: {}", e)
            return None

        if isinstance(result, dict):
            run_id = result.get("run_id")
            if isinstance(run_id, str) and run_id.strip():
                return run_id.strip()
        return None

    def _map_plan_steps_to_moirai(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return map_plan_steps_to_moirai(steps)

    async def _write_debug_snapshot(
        self,
        tree: ReasoningTree,
        *,
        user_id: str,
        policy: Dict[str, Any],
    ) -> None:
        await self.debug_snapshot_writer.write(tree, user_id=user_id, policy=policy)

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        return safe_user_segment(user_id)
