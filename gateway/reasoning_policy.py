from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from config import config as global_config

from .reasoning_utils import to_bool


class ReasoningPolicyResolver:
    """Resolve and normalize runtime reasoning policy from global and user config."""

    CONFIG_KEYS = (
        "enabled",
        "mode",
        "max_depth",
        "max_nodes",
        "max_iterations",
        "max_memory_calls",
        "max_tool_calls",
        "max_replan_rounds",
        "max_react_rounds_total",
        "target_runtime_seconds",
        "max_runtime_seconds",
        "max_low_yield_tool_failures",
        "plan_max_steps",
        "beam_width",
        "branch_factor",
        "candidate_votes",
        "min_branch_score",
        "moirai_export_plan",
        "moirai_auto_start",
        "workflow_tool_bridge",
        "failure_confidence_threshold",
        "debug_log",
    )

    def resolve(
        self,
        *,
        user_id: Optional[str],
        user_config: Optional[Dict[str, Any]],
        config_loader: Optional[Callable[[str], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        policy = self._defaults()
        cfg = user_config
        if cfg is None and config_loader and user_id:
            try:
                cfg = config_loader(user_id)
            except Exception:
                cfg = None
        if isinstance(cfg, dict):
            reasoning_cfg = cfg.get("reasoning", {})
            if isinstance(reasoning_cfg, dict):
                for key in self.CONFIG_KEYS:
                    if key in reasoning_cfg:
                        policy[key] = reasoning_cfg[key]
        return self._normalize(policy)

    def _defaults(self) -> Dict[str, Any]:
        global_reasoning: Dict[str, Any] = {}
        try:
            if hasattr(global_config, "reasoning"):
                global_reasoning = global_config.reasoning.model_dump()
        except Exception:
            global_reasoning = {}
        return {
            "enabled": bool(global_reasoning.get("enabled", True)),
            "mode": str(global_reasoning.get("mode", "react_tot")),
            "max_depth": int(global_reasoning.get("max_depth", 4)),
            "max_nodes": int(global_reasoning.get("max_nodes", 24)),
            "max_iterations": int(global_reasoning.get("max_iterations", 16)),
            "max_memory_calls": int(global_reasoning.get("max_memory_calls", 6)),
            "max_tool_calls": int(global_reasoning.get("max_tool_calls", 8)),
            "max_replan_rounds": int(global_reasoning.get("max_replan_rounds", 6)),
            "max_react_rounds_total": int(global_reasoning.get("max_react_rounds_total", 14)),
            "target_runtime_seconds": float(global_reasoning.get("target_runtime_seconds", 240.0)),
            "max_runtime_seconds": float(global_reasoning.get("max_runtime_seconds", 480.0)),
            "max_low_yield_tool_failures": int(global_reasoning.get("max_low_yield_tool_failures", 4)),
            "plan_max_steps": int(global_reasoning.get("plan_max_steps", 8)),
            "beam_width": int(global_reasoning.get("beam_width", 3)),
            "branch_factor": int(global_reasoning.get("branch_factor", 3)),
            "candidate_votes": int(global_reasoning.get("candidate_votes", 3)),
            "min_branch_score": float(global_reasoning.get("min_branch_score", 0.0)),
            "moirai_export_plan": bool(global_reasoning.get("moirai_export_plan", False)),
            "moirai_auto_start": bool(global_reasoning.get("moirai_auto_start", True)),
            "workflow_tool_bridge": bool(global_reasoning.get("workflow_tool_bridge", True)),
            "failure_confidence_threshold": float(global_reasoning.get("failure_confidence_threshold", 0.55)),
            "debug_log": bool(
                global_reasoning.get(
                    "debug_log",
                    bool(getattr(global_config.system, "debug", False)),
                )
            ),
        }

    @staticmethod
    def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
        policy["max_depth"] = max(1, int(policy["max_depth"]))
        policy["max_nodes"] = max(4, int(policy["max_nodes"]))
        policy["max_iterations"] = max(1, int(policy["max_iterations"]))
        policy["max_memory_calls"] = max(0, int(policy["max_memory_calls"]))
        policy["max_tool_calls"] = max(0, int(policy["max_tool_calls"]))
        policy["max_replan_rounds"] = max(0, int(policy["max_replan_rounds"]))
        policy["max_react_rounds_total"] = max(1, int(policy["max_react_rounds_total"]))
        policy["target_runtime_seconds"] = max(30.0, float(policy["target_runtime_seconds"]))
        policy["max_runtime_seconds"] = max(
            policy["target_runtime_seconds"],
            float(policy["max_runtime_seconds"]),
        )
        policy["max_low_yield_tool_failures"] = max(0, int(policy["max_low_yield_tool_failures"]))
        policy["plan_max_steps"] = max(1, int(policy["plan_max_steps"]))
        policy["beam_width"] = max(1, int(policy["beam_width"]))
        policy["branch_factor"] = max(1, int(policy["branch_factor"]))
        policy["candidate_votes"] = max(1, int(policy["candidate_votes"]))
        policy["min_branch_score"] = min(1.0, max(0.0, float(policy["min_branch_score"])))
        policy["moirai_export_plan"] = to_bool(policy.get("moirai_export_plan"), default=False)
        policy["moirai_auto_start"] = to_bool(policy.get("moirai_auto_start"), default=True)
        policy["workflow_tool_bridge"] = to_bool(policy.get("workflow_tool_bridge"), default=True)
        policy["failure_confidence_threshold"] = min(
            1.0,
            max(0.0, float(policy.get("failure_confidence_threshold", 0.55))),
        )
        policy["debug_log"] = to_bool(policy.get("debug_log"), default=False)
        policy["mode"] = str(policy.get("mode", "react_tot")).strip().lower() or "react_tot"
        return policy
