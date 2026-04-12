from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .reasoning_state_machine import PENDING


@dataclass
class ReasoningNode:
    node_id: str
    parent_id: Optional[str]
    kind: str
    title: str
    prompt: str = ""
    status: str = PENDING
    evidence: List[str] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    human_gate: Dict[str, Any] = field(default_factory=dict)
    verifier_state: Dict[str, Any] = field(default_factory=dict)
    checkpoint: Dict[str, Any] = field(default_factory=dict)
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
