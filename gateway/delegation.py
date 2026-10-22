"""Bounded in-process delegation; child execution stays in Conversation/Action."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from config import MultiAgentConfig, config
from .tools.projection import project_capability_snapshot


class DelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=16000)
    label: str = Field(min_length=1, max_length=120)
    tools: list[str] | None = Field(default=None, max_length=128)
    run_in_background: bool = True


@dataclass
class _Budget:
    count: int = 0
    active: int = 0
    closed: bool = False


@dataclass
class DelegationScope:
    budget: _Budget
    depth: int = 0
    allowed_tools: frozenset[str] | None = None
    parent_action_loop_id: str | None = None
    ancestor_action_loop_ids: tuple[str, ...] = ()
    closed: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    agent_task_id: str | None = None
    workspace_id: str | None = None
    background_notification: bool = False


_scope: ContextVar[DelegationScope | None] = ContextVar("delegation_scope", default=None)


def current_delegation() -> DelegationScope | None:
    return _scope.get()


def take_delegated_usage() -> dict[str, int]:
    scope = current_delegation()
    if scope is None:
        return {}
    usage = dict(scope.usage)
    scope.usage.clear()
    return usage


def delegation_enabled(run_context: Any, user_config: dict | None) -> bool:
    payload = getattr(run_context, "input_payload", {}) or {}
    metadata = payload.get("metadata") or {}
    return (
        config.multi_agent.enabled
        and (user_config or {}).get("multi_agent", {}).get("enabled", True) is True
        and metadata.get("multi_agent") is True
        and bool(getattr(run_context, "user_id", None))
    )


def delegation_limits(user_config):
    settings = MultiAgentConfig(**{**config.multi_agent.model_dump(), **((user_config or {}).get("multi_agent") or {})})
    return {key: min(getattr(config.multi_agent, key), getattr(settings, key)) for key in (
        "max_children", "max_parallel", "max_depth", "child_steps", "child_max_tokens", "timeout_s", "result_chars",
    )}


def child_configuration(user_config, limits):
    result = deepcopy(user_config or {})
    result.setdefault("action", {}).setdefault("gaps", {})["enabled"] = False
    api = result.setdefault("api", {})
    api["max_tokens"] = min(int(api.get("max_tokens") or config.api.max_tokens), limits["child_max_tokens"])
    return result


class DelegationRuntime:
    """Own only admission and child lifetime, not a second agent loop or tool catalog."""

    def __init__(self) -> None:
        self._active = 0

    @contextmanager
    def turn(self, *, spent: int = 0):
        if current_delegation() is not None:
            yield current_delegation()
            return
        scope = DelegationScope(_Budget(count=max(0, int(spent))))
        token = _scope.set(scope)
        try:
            yield scope
        finally:
            scope.budget.closed = True
            _scope.reset(token)

    async def delegate(self, conversation: Any, request: DelegationRequest, *, parent: Any, user_config: dict | None) -> dict:
        scope = current_delegation()
        if scope is None or scope.closed or scope.budget.closed or not delegation_enabled(parent, user_config):
            raise PermissionError("Multi-agent delegation is not enabled for this turn")
        # Deployment values are ceilings; account overrides may only narrow them.
        limits = delegation_limits(user_config)
        def occupied():
            background = getattr(conversation, "background_agents", None)
            return self._active + (background.active_count() if background is not None else 0)
        if scope.depth >= limits["max_depth"]:
            raise PermissionError("Delegation depth limit reached")
        if scope.budget.count >= limits["max_children"]:
            raise PermissionError("Delegation turn budget exhausted")
        # Reject rather than queue while ancestors hold slots: nested fan-out cannot deadlock.
        if scope.budget.active >= limits["max_parallel"] or occupied() >= limits["max_parallel"]:
            raise PermissionError("Delegation capacity is occupied; collect current work before retrying")

        capability = conversation.capability_service
        catalog = await capability.get_tool_catalog(run_context=parent, user_config=user_config)
        allowed = frozenset(row["name"] for row in project_capability_snapshot(catalog, schema_budget_chars=0)["compact_index"] if row["callable_now"])
        if request.tools is not None:
            selected = frozenset(request.tools)
            if not selected <= allowed:
                raise PermissionError("Requested child tools are not available to the parent")
            allowed &= selected
        # No await between final admission and accounting.
        if scope.budget.count >= limits["max_children"] or scope.budget.active >= limits["max_parallel"] or occupied() >= limits["max_parallel"]:
            raise PermissionError("Delegation capacity or budget exhausted")
        child_id = f"child_{uuid4().hex}"
        child = deepcopy(parent)
        child.action_loop_id = None
        child.conversation_turn_id = child_id
        for field in ("tool_availability", "self_model_context", "cognition_snapshot", "action_state", "goal_gaps", "reasoning_state", "prompt_blocks"):
            setattr(child, field, {})
        child.registered_tools = []
        child.input_payload = {"message": request.objective, "metadata": {
            **dict((getattr(parent, "input_payload", {}) or {}).get("metadata") or {}),
            "delegation_id": child_id,
        }}
        child_config = child_configuration(user_config, limits)
        scope.budget.count += 1
        scope.budget.active += 1
        self._active += 1
        parent_loop = getattr(parent, "action_loop_id", None)
        child_scope = DelegationScope(
            scope.budget, scope.depth + 1, allowed, parent_loop,
            (*scope.ancestor_action_loop_ids, parent_loop) if parent_loop else scope.ancestor_action_loop_ids,
        )
        child_scope.workspace_id = (getattr(parent, "workspace_handle", {}) or {}).get("workspace_id") or getattr(parent, "session_id", None)
        token = _scope.set(child_scope)
        outcome = {"child_id": child_id, "label": request.label, "status": "failed", "output": ""}
        try:
            async with asyncio.timeout(limits["timeout_s"]):
                result = await conversation.run_delegated_turn(
                    objective=request.objective, label=request.label, run_context=child,
                    user_config=child_config, max_steps=limits["child_steps"],
                )
            status = str(result.get("status") or "failed")
            for key in ("prompt_tokens", "completion_tokens"):
                scope.usage[key] = scope.usage.get(key, 0) + max(0, int((result.get("usage") or {}).get(key) or 0))
            outcome.update(
                status="completed" if status == "success" else status,
                output=str(result.get("content") or "")[:limits["result_chars"]],
                truncated=len(str(result.get("content") or "")) > limits["result_chars"],
                action_loop_id=result.get("action_run_id"), usage=result.get("usage"),
            )
            if outcome["status"] != "completed":
                outcome["error_detail"] = {
                    "code": "SUBAGENT_INCOMPLETE", "message": outcome["output"] or f"Child stopped: {outcome['status']}",
                    "details": {"child_id": child_id, "status": outcome["status"]},
                }
            return {"ok": outcome["status"] == "completed", **outcome}
        except TimeoutError:
            return {"ok": False, **outcome, "status": "timed_out", "error": "Delegated task exceeded its deadline"}
        finally:
            child_scope.closed = True
            _scope.reset(token)
            scope.budget.active -= 1
            self._active -= 1


@contextmanager
def bind_delegation(scope):
    token = _scope.set(scope)
    try:
        yield
    finally:
        scope.closed = True
        _scope.reset(token)
