from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Dict, Optional, Set

from .spec import SideEffectLevel, ToolSpec


@dataclass
class ToolPolicyDecision:
    allowed: bool
    reason: str
    requires_confirmation: bool = False
    effective: Dict[str, Any] | None = None


class ToolPolicy:
    """Policy checks for tool invocation with side-effect-safe defaults."""

    def __init__(self) -> None:
        self.default_mode = "fast"

    def evaluate(
        self,
        *,
        spec: ToolSpec,
        run_context: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> ToolPolicyDecision:
        effective = self._effective_policy(run_context=run_context, user_config=user_config)

        candidates = {spec.tool_name, spec.full_name}

        if self._matches_any(candidates, effective["deny"]):
            return ToolPolicyDecision(False, f"blocked by denylist: {spec.full_name}", effective=effective)

        mode = str(effective.get("mode") or self.default_mode)
        mode_restrictions = effective.get("mode_restrictions", {})
        if isinstance(mode_restrictions, dict) and mode in mode_restrictions:
            allowed_for_mode = self._to_set(mode_restrictions.get(mode))
            if allowed_for_mode and not self._matches_any(candidates, allowed_for_mode):
                return ToolPolicyDecision(False, f"blocked in mode '{mode}': {spec.full_name}", effective=effective)

        allowed_explicitly = self._matches_any(candidates, effective["allow"]) or self._matches_any(
            candidates, effective["skill_allowlist"]
        )

        if spec.side_effect_level != SideEffectLevel.READ_ONLY and not allowed_explicitly:
            return ToolPolicyDecision(
                False,
                f"side-effect tool requires explicit allow: {spec.full_name}",
                effective=effective,
            )

        requires_confirmation = spec.side_effect_level in {
            SideEffectLevel.EXTERNAL_WRITE,
            SideEffectLevel.PRIVILEGED_HOST_ACTION,
        }

        if effective["allow"] and not self._matches_any(candidates, effective["allow"]):
            return ToolPolicyDecision(False, f"not in allowlist: {spec.full_name}", effective=effective)

        return ToolPolicyDecision(
            True,
            "allowed by policy",
            requires_confirmation=requires_confirmation,
            effective=effective,
        )

    def _effective_policy(
        self,
        *,
        run_context: Optional[Any],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        allow: Set[str] = set()
        deny: Set[str] = set()
        skill_allowlist: Set[str] = set()
        mode_restrictions: Dict[str, Any] = {}

        tools_cfg = {}
        if isinstance(user_config, dict) and isinstance(user_config.get("tools"), dict):
            tools_cfg = user_config.get("tools", {})

        allow |= self._to_set(tools_cfg.get("allow"))
        deny |= self._to_set(tools_cfg.get("deny"))
        skill_allowlist |= self._to_set(tools_cfg.get("skill_allowlist"))

        mode = ""
        if run_context is not None:
            mode = str(getattr(run_context, "requested_mode", "") or "")
            context_policy = getattr(run_context, "tool_policy", None)
            if isinstance(context_policy, dict):
                allow |= self._to_set(context_policy.get("allow"))
                deny |= self._to_set(context_policy.get("deny"))
                skill_allowlist |= self._to_set(context_policy.get("skill_allowlist"))
                if isinstance(context_policy.get("mode_restrictions"), dict):
                    mode_restrictions = dict(context_policy.get("mode_restrictions") or {})

        if not mode and run_context is not None:
            session_state = getattr(run_context, "session_state", None)
            mode = str(getattr(session_state, "reasoning_mode", "") or "")

        return {
            "allow": allow,
            "deny": deny,
            "skill_allowlist": skill_allowlist,
            "mode": mode or self.default_mode,
            "mode_restrictions": mode_restrictions,
        }

    @staticmethod
    def _to_set(value: Any) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            v = value.strip()
            return {v} if v else set()
        if isinstance(value, (list, tuple, set)):
            out: Set[str] = set()
            for item in value:
                if isinstance(item, str):
                    s = item.strip()
                    if s:
                        out.add(s)
            return out
        return set()

    @staticmethod
    def _matches_any(names: Set[str], rules: Set[str]) -> bool:
        if not rules:
            return False
        if "*" in rules:
            return True
        for rule in rules:
            for name in names:
                if fnmatch(name, rule):
                    return True
        return False
