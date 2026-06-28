from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from .reasoning_models import ReasoningNode, ReasoningTree
from .reasoning_state_machine import (
    RUNNING,
    SKIPPED,
    SUCCEEDED,
    can_transition,
)


class ReasoningTreeRuntime:
    """Tree mutation and serialization boundary for runtime reasoning traces."""

    def create_tree(self, *, session_id: str, user_id: str, root_goal: str) -> ReasoningTree:
        tree = ReasoningTree(
            tree_id=uuid.uuid4().hex,
            session_id=session_id,
            user_id=user_id,
            root_goal=root_goal,
        )
        root = self.add_node(tree, parent_id=None, kind="root", title=root_goal)
        tree.root_node_id = root.node_id
        return tree

    def add_node(
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

    def transition_node_status(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        target: str,
        reason: str = "",
        checkpoint: Optional[Dict[str, Any]] = None,
    ) -> None:
        current = str(node.status or "").strip()
        target_status = str(target or "").strip()
        if current == target_status:
            return
        if not can_transition(current, target_status):
            raise ValueError(f"invalid node status transition: {current} -> {target_status}")
        node.status = target_status
        node.updated_at = time.time()
        if checkpoint:
            node.checkpoint = dict(checkpoint)
        if reason:
            node.metadata["status_reason"] = reason
        tree.updated_at = time.time()

    def mark_node_succeeded(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        observation: str,
        evidence: Optional[list[str]] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.transition_node_status(
            tree=tree,
            node=node,
            target=SUCCEEDED,
            reason="step_completed",
        )
        node.observation = observation
        node.summary = observation
        node.evidence = list(evidence or [])
        node.result = dict(result or {})

    def resume_node_from_waiting_tool(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        note: str = "tool_observation_ready",
    ) -> None:
        self.transition_node_status(tree=tree, node=node, target=RUNNING, reason=note)

    def resume_node_from_waiting_human(
        self,
        *,
        tree: ReasoningTree,
        node: ReasoningNode,
        approved: bool,
    ) -> None:
        if approved:
            self.transition_node_status(
                tree=tree,
                node=node,
                target=RUNNING,
                reason="human_approved",
            )
            return
        self.transition_node_status(
            tree=tree,
            node=node,
            target=SKIPPED,
            reason="human_rejected",
        )

    @staticmethod
    def snapshot_node(node: ReasoningNode) -> Dict[str, Any]:
        return {
            "node_id": node.node_id,
            "status": node.status,
            "checkpoint": dict(node.checkpoint or {}),
            "tool_calls": list(node.tool_calls or []),
            "human_gate": dict(node.human_gate or {}),
            "verifier_state": dict(node.verifier_state or {}),
        }

    @staticmethod
    def node_depth(tree: ReasoningTree, node_id: Optional[str]) -> int:
        depth = 0
        current = tree.nodes.get(node_id) if node_id else None
        while current and current.parent_id:
            depth += 1
            current = tree.nodes.get(current.parent_id)
        return depth

    @staticmethod
    def serialize_tree_payload(
        payload: Dict[str, Any],
        *,
        include_nodes: bool,
        control: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tree_id = str(payload.get("tree_id", "") or "")
        control = control or {}
        nodes = payload.get("nodes", [])
        if include_nodes and isinstance(nodes, list):
            node_rows = [
                {
                    "node_id": str(node.get("node_id", "")),
                    "parent_id": node.get("parent_id"),
                    "kind": str(node.get("kind", "")),
                    "title": str(node.get("title", "")),
                    "status": str(node.get("status", "")),
                    "observation": str(node.get("observation", "") or ""),
                    "summary": str(node.get("summary", "") or ""),
                    "updated_at": float(node.get("updated_at") or 0.0),
                }
                for node in nodes
                if isinstance(node, dict)
            ]
        else:
            node_rows = []
        return {
            "tree_id": tree_id,
            "session_id": str(payload.get("session_id", "") or ""),
            "user_id": str(payload.get("user_id", "") or ""),
            "root_goal": str(payload.get("root_goal", "") or ""),
            "status": str(payload.get("status", "") or ""),
            "created_at": float(payload.get("created_at") or 0.0),
            "updated_at": float(payload.get("updated_at") or 0.0),
            "stats": dict(payload.get("stats", {}) or {}),
            "root_node_id": payload.get("root_node_id"),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "nodes": node_rows,
            "control": serialize_control(control),
            "source": "pending_outcome",
        }

    @staticmethod
    def serialize_tree(
        tree: ReasoningTree,
        *,
        include_nodes: bool,
        control: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if include_nodes:
            node_rows = [
                {
                    "node_id": node.node_id,
                    "parent_id": node.parent_id,
                    "kind": node.kind,
                    "title": node.title,
                    "status": node.status,
                    "observation": node.observation,
                    "summary": node.summary,
                    "updated_at": node.updated_at,
                }
                for node in tree.nodes.values()
            ]
            node_rows.sort(key=lambda it: float(it.get("updated_at") or 0.0), reverse=True)
        else:
            node_rows = []
        return {
            "tree_id": tree.tree_id,
            "session_id": tree.session_id,
            "user_id": tree.user_id,
            "root_goal": tree.root_goal,
            "status": tree.status,
            "created_at": tree.created_at,
            "updated_at": tree.updated_at,
            "stats": dict(tree.stats),
            "root_node_id": tree.root_node_id,
            "node_count": len(tree.nodes),
            "nodes": node_rows,
            "control": serialize_control(control or {}),
            "source": "active",
        }


def serialize_control(control: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stop_requested": bool(control.get("stop_requested")),
        "stop_reason": str(control.get("stop_reason", "") or ""),
        "pending_steering_notes": len(control.get("steering_notes", []) or []),
    }
