from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict

from .reasoning_models import ReasoningTree


@dataclass
class ReasoningBudgetLedger:
    """Global cost ledger for a reasoning tree.

    ReAct remains responsible for choosing the next action. This ledger only
    exposes runtime pressure and low-yield external-action signals so ReAct can
    choose synthesis over more expensive exploration when appropriate.
    """

    default_target_runtime_seconds: float = 240.0
    default_max_runtime_seconds: float = 480.0
    default_max_react_rounds_total: int = 14
    default_max_low_yield_tool_failures: int = 4

    def build(self, tree: ReasoningTree, policy: Dict[str, Any]) -> Dict[str, Any]:
        elapsed = max(0.0, time.time() - float(tree.created_at or time.time()))
        target_seconds = float(
            policy.get("target_runtime_seconds", self.default_target_runtime_seconds)
            or self.default_target_runtime_seconds
        )
        max_seconds = float(
            policy.get("max_runtime_seconds", self.default_max_runtime_seconds)
            or self.default_max_runtime_seconds
        )
        react_rounds = int(tree.stats.get("react_rounds", 0) or 0)
        max_react_rounds = int(
            policy.get("max_react_rounds_total", self.default_max_react_rounds_total)
            or self.default_max_react_rounds_total
        )
        tool_calls = int(tree.stats.get("tool_calls", 0) or 0)
        tool_failures = int(tree.stats.get("tool_failures", 0) or 0)
        react_failed_observations = int(tree.stats.get("react_failed_observations", 0) or 0)
        low_yield_failures = max(tool_failures, react_failed_observations)
        max_low_yield_failures = int(
            policy.get("max_low_yield_tool_failures", self.default_max_low_yield_tool_failures)
            or self.default_max_low_yield_tool_failures
        )
        failure_ratio = float(low_yield_failures / tool_calls) if tool_calls > 0 else 0.0
        return {
            "elapsed_seconds": round(elapsed, 2),
            "target_runtime_seconds": target_seconds,
            "max_runtime_seconds": max_seconds,
            "runtime_over_target": elapsed >= target_seconds,
            "runtime_exhausted": elapsed >= max_seconds,
            "react_rounds": react_rounds,
            "max_react_rounds_total": max_react_rounds,
            "react_rounds_exhausted": react_rounds >= max_react_rounds,
            "tool_calls": tool_calls,
            "max_tool_calls": int(policy.get("max_tool_calls", 0) or 0),
            "tool_failures": tool_failures,
            "react_failed_observations": react_failed_observations,
            "low_yield_tool_failures": low_yield_failures,
            "max_low_yield_tool_failures": max_low_yield_failures,
            "tool_failure_ratio": round(failure_ratio, 3),
            "low_yield_tools": (
                max_low_yield_failures > 0
                and low_yield_failures >= max_low_yield_failures
                and failure_ratio >= 0.5
            ),
        }

    @staticmethod
    def should_stop_reasoning(ledger: Dict[str, Any]) -> bool:
        return bool(ledger.get("runtime_exhausted") or ledger.get("react_rounds_exhausted"))

    @staticmethod
    def should_avoid_external_actions(ledger: Dict[str, Any]) -> bool:
        return bool(
            ledger.get("runtime_over_target")
            or ledger.get("react_rounds_exhausted")
            or ledger.get("low_yield_tools")
        )
