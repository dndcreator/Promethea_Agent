from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from config import config as global_config

from .events import EventEmitter
from .protocol import EventType
from .tool_service import ToolInvocationContext


@dataclass
class ReasoningNode:
    node_id: str
    parent_id: Optional[str]
    kind: str
    title: str
    prompt: str = ""
    status: str = "pending"
    observation: str = ""
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class ReasoningTree:
    tree_id: str
    session_id: str
    user_id: str
    root_goal: str
    status: str = "running"
    nodes: Dict[str, ReasoningNode] = field(default_factory=dict)
    root_node_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stats: Dict[str, Any] = field(
        default_factory=lambda: {
            "iterations": 0,
            "memory_calls": 0,
            "tool_calls": 0,
            "think_calls": 0,
        }
    )


class ReasoningService:
    """Runtime reasoning tree service."""

    def __init__(
        self,
        event_emitter: Optional[EventEmitter] = None,
        conversation_core: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        tool_service: Optional[Any] = None,
        config_service: Optional[Any] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core
        self.memory_service = memory_service
        self.tool_service = tool_service
        self.config_service = config_service
        self._active_trees: Dict[str, ReasoningTree] = {}
        self._completed_runs = 0
        self._failed_runs = 0

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
            "completed_runs": self._completed_runs,
            "failed_runs": self._failed_runs,
        }

    def _resolve_policy(
        self,
        *,
        user_id: Optional[str],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        global_reasoning = {}
        try:
            if hasattr(global_config, "reasoning"):
                global_reasoning = global_config.reasoning.model_dump()
        except Exception:
            global_reasoning = {}
        policy: Dict[str, Any] = {
            "enabled": bool(global_reasoning.get("enabled", False)),
            "mode": str(global_reasoning.get("mode", "react_tot")),
            "max_depth": int(global_reasoning.get("max_depth", 4)),
            "max_nodes": int(global_reasoning.get("max_nodes", 24)),
            "max_iterations": int(global_reasoning.get("max_iterations", 10)),
            "max_memory_calls": int(global_reasoning.get("max_memory_calls", 4)),
            "max_tool_calls": int(global_reasoning.get("max_tool_calls", 4)),
            "max_replan_rounds": int(global_reasoning.get("max_replan_rounds", 3)),
            "plan_max_steps": int(global_reasoning.get("plan_max_steps", 5)),
            "beam_width": int(global_reasoning.get("beam_width", 3)),
            "branch_factor": int(global_reasoning.get("branch_factor", 3)),
            "candidate_votes": int(global_reasoning.get("candidate_votes", 3)),
            "min_branch_score": float(global_reasoning.get("min_branch_score", 0.0)),
            "debug_log": bool(
                global_reasoning.get(
                    "debug_log",
                    bool(getattr(global_config.system, "debug", False)),
                )
            ),
        }
        cfg = user_config
        if cfg is None and self.config_service and user_id:
            try:
                cfg = self.config_service.get_merged_config(user_id)
            except Exception:
                cfg = None
        if isinstance(cfg, dict):
            reasoning_cfg = cfg.get("reasoning", {})
            for key in (
                "enabled",
                "mode",
                "max_depth",
                "max_nodes",
                "max_iterations",
                "max_memory_calls",
                "max_tool_calls",
                "max_replan_rounds",
                "plan_max_steps",
                "beam_width",
                "branch_factor",
                "candidate_votes",
                "min_branch_score",
                "debug_log",
            ):
                if key in reasoning_cfg:
                    policy[key] = reasoning_cfg[key]
        policy["max_depth"] = max(1, int(policy["max_depth"]))
        policy["max_nodes"] = max(4, int(policy["max_nodes"]))
        policy["max_iterations"] = max(1, int(policy["max_iterations"]))
        policy["max_memory_calls"] = max(0, int(policy["max_memory_calls"]))
        policy["max_tool_calls"] = max(0, int(policy["max_tool_calls"]))
        policy["max_replan_rounds"] = max(0, int(policy["max_replan_rounds"]))
        policy["plan_max_steps"] = max(1, int(policy["plan_max_steps"]))
        policy["beam_width"] = max(1, int(policy["beam_width"]))
        policy["branch_factor"] = max(1, int(policy["branch_factor"]))
        policy["candidate_votes"] = max(1, int(policy["candidate_votes"]))
        policy["min_branch_score"] = min(1.0, max(0.0, float(policy["min_branch_score"])))
        policy["debug_log"] = bool(policy["debug_log"])
        policy["mode"] = str(policy.get("mode", "react_tot")).strip().lower() or "react_tot"
        return policy

    def _create_tree(self, *, session_id: str, user_id: str, root_goal: str) -> ReasoningTree:
        tree = ReasoningTree(
            tree_id=uuid.uuid4().hex,
            session_id=session_id,
            user_id=user_id,
            root_goal=root_goal,
        )
        root = self._add_node(tree, parent_id=None, kind="root", title=root_goal)
        tree.root_node_id = root.node_id
        return tree

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
        node = ReasoningNode(
            node_id=uuid.uuid4().hex,
            parent_id=parent_id,
            kind=kind,
            title=title,
            prompt=prompt,
            metadata=metadata or {},
        )
        tree.nodes[node.node_id] = node
        tree.updated_at = time.time()
        if parent_id and parent_id in tree.nodes:
            tree.nodes[parent_id].children.append(node.node_id)
            tree.nodes[parent_id].updated_at = time.time()
        return node

    def _node_depth(self, tree: ReasoningTree, node_id: Optional[str]) -> int:
        depth = 0
        current = tree.nodes.get(node_id) if node_id else None
        while current and current.parent_id:
            depth += 1
            current = tree.nodes.get(current.parent_id)
        return depth

    async def _emit(self, event: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        try:
            await self.event_emitter.emit(event, payload)
        except Exception as e:
            logger.debug("ReasoningService emit failed {}: {}", event, e)

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
        is_complex = self._to_bool(gate.get("needs_reasoning", False), default=False)
        needs_memory = self._to_bool(gate.get("needs_memory", False), default=False)
        needs_tools = self._to_bool(gate.get("needs_tools", False), default=False)

        # Keep the fast path for normal/simple chats. Only enter react-only for
        # simple requests that explicitly need memory/tool interaction.
        if not is_complex and not needs_memory and not needs_tools:
            return {"used_reasoning": False, "gate": gate}

        tree = self._create_tree(session_id=session_id, user_id=user_id, root_goal=user_message)
        self._active_trees[tree.tree_id] = tree
        await self._emit(
            EventType.REASONING_START,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "goal": user_message,
                "gate": gate,
                "mode": "tot_react" if is_complex else "react_only",
            },
        )
        try:
            steps: List[Dict[str, Any]] = []
            if is_complex:
                steps = await self._plan_steps(
                    tree=tree,
                    user_message=user_message,
                    recent_messages=recent_messages,
                    user_config=user_config,
                    user_id=user_id,
                    policy=policy,
                    max_candidates=max(
                        policy["plan_max_steps"],
                        policy["beam_width"] * policy["branch_factor"],
                    ),
                )
            else:
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
                tree.status = "completed"
                return {"used_reasoning": False, "gate": gate}

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

            while frontier and tree.stats["iterations"] < iteration_budget:
                next_candidates: List[str] = []
                for node_id in frontier:
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
                    )
                    for step in extra_steps:
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

            tree.status = "max_iterations" if tree.stats["iterations"] >= iteration_budget else "completed"
            reasoning_summary = await self._summarize_tree(
                tree=tree,
                user_message=user_message,
                user_config=user_config,
                user_id=user_id,
            )
            final_prompt = base_system_prompt.strip()
            if reasoning_summary:
                extra = (
                    "Internal reasoning context. Use it to improve the answer. "
                    "Do not mention this reasoning process explicitly.\n"
                    f"{reasoning_summary}"
                )
                final_prompt = f"{final_prompt}\n\n{extra}" if final_prompt else extra

            tree.updated_at = time.time()
            self._completed_runs += 1
            await self._emit(
                EventType.REASONING_COMPLETE,
                {
                    "tree_id": tree.tree_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": tree.status,
                    "stats": tree.stats,
                },
            )
            await self._write_debug_snapshot(tree, user_id=user_id, policy=policy)
            return {
                "used_reasoning": True,
                "tree_id": tree.tree_id,
                "system_prompt": final_prompt,
                "reasoning_summary": reasoning_summary,
                "gate": gate,
                "status": tree.status,
            }
        except Exception:
            tree.status = "failed"
            self._failed_runs += 1
            await self._emit(
                EventType.REASONING_ERROR,
                {
                    "tree_id": tree.tree_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": tree.status,
                },
            )
            await self._write_debug_snapshot(tree, user_id=user_id, policy=policy)
            raise
        finally:
            self._active_trees.pop(tree.tree_id, None)

    async def _gate_reasoning(
        self,
        *,
        user_message: str,
        recent_messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        heuristic = self._heuristic_gate(user_message)
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
        merged["needs_reasoning"] = bool(
            merged.get("needs_reasoning", heuristic["needs_reasoning"])
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
    ) -> List[Dict[str, Any]]:
        node = tree.nodes[node_id]
        node.status = "running"
        node.updated_at = time.time()
        await self._emit_node(tree, node, EventType.REASONING_NODE_CREATED)
        observations: List[str] = []
        step = dict(node.metadata)
        extra_steps: List[Dict[str, Any]] = []

        # ReAct loop: Thought(node) -> Action(decision) -> Observation -> repeat.
        if step.get("requires_memory") and tree.stats["memory_calls"] < policy["max_memory_calls"]:
            memory_query = step.get("memory_query") or step.get("goal") or node.title
            memory_observation = await self._run_memory_lookup(
                tree=tree,
                node=node,
                session_id=session_id,
                user_id=user_id,
                query=memory_query,
            )
            if memory_observation:
                observations.append(f"Memory:\n{memory_observation}")

        react_rounds = max(1, int(policy["max_replan_rounds"]) + 1)
        for _ in range(react_rounds):
            decision = await self._replan_step(
                tree=tree,
                node=node,
                user_message=user_message,
                observations=observations,
                user_config=user_config,
                user_id=user_id,
            )
            next_action = (decision.get("next_action") or "done").lower()
            extra_steps.extend(
                step for step in decision.get("additional_steps", []) if isinstance(step, dict)
            )
            if next_action == "memory" and tree.stats["memory_calls"] < policy["max_memory_calls"]:
                query = decision.get("memory_query") or node.title
                memory_observation = await self._run_memory_lookup(
                    tree=tree,
                    node=node,
                    session_id=session_id,
                    user_id=user_id,
                    query=query,
                )
                if memory_observation:
                    observations.append(f"Memory:\n{memory_observation}")
                continue

            if next_action == "tool" and tree.stats["tool_calls"] < policy["max_tool_calls"]:
                tool_step = {
                    "goal": node.title,
                    "tool_intent": decision.get("tool_intent")
                    or step.get("tool_intent")
                    or node.title,
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
                )
                if tool_observation:
                    observations.append(f"Tool:\n{tool_observation}")
                continue

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

        if not observations:
            # Fallback to a single thought note, so simple tasks still produce traceable reasoning.
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

        if not extra_steps and observations and self._node_depth(tree, node_id) < policy["max_depth"]:
            expanded = await self._plan_steps(
                tree=tree,
                user_message=user_message,
                recent_messages=recent_messages,
                user_config=user_config,
                user_id=user_id,
                policy=policy,
                max_candidates=policy["branch_factor"],
                observation_context="\n\n".join(observations),
            )
            extra_steps.extend(expanded)

        node.status = "completed"
        node.summary = "\n\n".join(observations).strip()
        node.observation = node.summary
        node.updated_at = time.time()
        await self._emit_node(tree, node, EventType.REASONING_NODE_COMPLETED)
        return extra_steps[: policy["branch_factor"]]

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
        payload = {
            "stage": stage,
            "task": user_message,
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
    ) -> str:
        if not self.memory_service or not self.memory_service.is_enabled():
            return ""
        child = self._add_node(
            tree,
            parent_id=node.node_id,
            kind="memory",
            title=f"memory: {query}",
            metadata={"query": query},
        )
        await self._emit(
            EventType.REASONING_MEMORY_REQUESTED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "query": query,
            },
        )
        try:
            result = await self.memory_service.get_context(
                query=query,
                session_id=session_id,
                user_id=user_id,
            )
        except Exception as e:
            result = f"[memory error] {e}"
        child.status = "completed"
        child.observation = result or ""
        child.summary = child.observation
        child.updated_at = time.time()
        tree.stats["memory_calls"] += 1
        await self._emit(
            EventType.REASONING_OBSERVATION_RECEIVED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "kind": "memory",
            },
        )
        return child.observation

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
    ) -> str:
        if not self.tool_service:
            return ""
        catalog = await self.tool_service.get_tool_catalog()
        if not catalog:
            return ""
        selected = await self._select_tool(
            step=step,
            user_message=user_message,
            observations=observations,
            catalog=catalog,
            user_config=user_config,
            user_id=user_id,
        )
        if not selected.get("use_tool"):
            return ""

        tool_type = selected.get("tool_type") or "mcp"
        service_name = selected.get("service_name") or selected.get("tool_name")
        tool_name = selected.get("tool_name") or service_name
        args = selected.get("args") or {}
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
            },
        )
        ctx = ToolInvocationContext(
            session_id=session_id,
            user_id=user_id,
            source="reasoning",
            metadata={"tree_id": tree.tree_id, "node_id": child.node_id},
        )
        try:
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
            )
        except Exception as e:
            result = f"[tool error] {e}"
        child.status = "completed"
        child.observation = self._stringify_observation(result)
        child.summary = child.observation
        child.updated_at = time.time()
        tree.stats["tool_calls"] += 1
        await self._emit(
            EventType.REASONING_OBSERVATION_RECEIVED,
            {
                "tree_id": tree.tree_id,
                "session_id": session_id,
                "user_id": user_id,
                "node_id": child.node_id,
                "kind": "tool",
            },
        )
        return child.observation

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
        catalog_text = "\n".join(
            f"- type={item.get('tool_type', 'unknown')} service={item['service_name']} "
            f"tool={item['tool_name']} desc={item.get('description', '')}"
            for item in catalog[:40]
        )
        prompt = (
            "Choose at most one tool for the current reasoning step. Return strict JSON: "
            "{\"use_tool\":bool,\"tool_type\":string,\"service_name\":string,\"tool_name\":string,"
            "\"args\":object,\"why\":string}."
        )
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Overall task:\n{user_message}\n\n"
                        f"Current step:\n{json.dumps(step, ensure_ascii=False)}\n\n"
                        f"Current observations:\n{self._truncate_text(chr(10).join(observations), 2000)}\n\n"
                        f"Available tools:\n{catalog_text}"
                    ),
                },
            ],
            user_config=user_config,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"use_tool": False}
        result["use_tool"] = bool(result.get("use_tool"))
        return result

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
        child.status = "completed"
        child.observation = response
        child.summary = response
        child.updated_at = time.time()
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
    ) -> Dict[str, Any]:
        prompt = (
            "Review the current reasoning step and decide the next action. Return strict JSON: "
            "{\"next_action\":\"done|memory|tool|think\",\"memory_query\":string,"
            "\"tool_intent\":string,\"additional_steps\":[{\"title\":string,\"goal\":string,"
            "\"requires_memory\":bool,\"memory_query\":string,\"requires_tools\":bool,"
            "\"tool_intent\":string,\"notes\":string}]}"
        )
        result = await self._call_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{user_message}\n\n"
                        f"Current step:\n{node.title}\n\n"
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
            "Summarize the reasoning results into concise internal context for the final assistant answer. "
            "Return plain text only. Include relevant memory/tool findings, constraints, and conclusions."
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
        if not text:
            return {}
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}

    def _format_recent_messages(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return "(none)"
        formatted = []
        for item in messages[-6:]:
            role = item.get("role", "unknown")
            content = self._truncate_text(str(item.get("content", "")), 300)
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)

    def _truncate_text(self, text: str, limit: int) -> str:
        if len(text or "") <= limit:
            return text or ""
        return (text or "")[: limit - 3] + "..."

    def _stringify_observation(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    @staticmethod
    def _to_bool(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off", ""}:
                return False
            return default
        return bool(value)

    async def _write_debug_snapshot(
        self,
        tree: ReasoningTree,
        *,
        user_id: str,
        policy: Dict[str, Any],
    ) -> None:
        if not policy.get("debug_log"):
            return
        try:
            user_dir = Path(global_config.system.log_dir) / self._safe_user_segment(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d")
            path = user_dir / f"{day}.reasoning.jsonl"
            payload = {
                "timestamp": time.time(),
                "tree": {
                    "tree_id": tree.tree_id,
                    "session_id": tree.session_id,
                    "user_id": tree.user_id,
                    "root_goal": tree.root_goal,
                    "status": tree.status,
                    "created_at": tree.created_at,
                    "updated_at": tree.updated_at,
                    "stats": tree.stats,
                    "root_node_id": tree.root_node_id,
                    "nodes": [asdict(node) for node in tree.nodes.values()],
                },
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("ReasoningService debug snapshot failed: {}", e)

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip() or "default_user"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
        return safe[:128] or "default_user"
