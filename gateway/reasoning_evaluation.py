"""Reasoning evaluation requests and bounded samples, without run-state authority."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .reasoning_models import ReasoningTree
from .reasoning_utils import truncate_text


async def judge_task_success(
    call_json: Callable[..., Awaitable[Any]],
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
        "assistant_output": truncate_text(assistant_output or "", 3000),
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
    result = await call_json(
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


def collect_observation_samples(
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
        if _looks_like_failure_observation(obs):
            if len(failed) < max(1, int(limit)):
                failed.append(truncate_text(obs, 500))
        elif len(succeeded) < max(1, int(limit)):
            succeeded.append(truncate_text(obs, 500))
    return {"failed": failed, "succeeded": succeeded}


async def judge_runtime_feasibility(
    call_json: Callable[..., Awaitable[Any]],
    *,
    user_message: str,
    tree: ReasoningTree,
    policy: Dict[str, Any],
    iteration_budget: int,
    user_config: Optional[Dict[str, Any]],
    user_id: Optional[str],
) -> Dict[str, Any]:
    samples = collect_observation_samples(tree=tree, limit=6)
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
    result = await call_json(
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
