from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Dict, Optional, Set


TOOLS_GROUPS: Dict[str, Set[str]] = {
    # OpenClaw-aligned conceptual groups adapted to this codebase.
    "browser": {
        "computer_control.browser_action",
        "computer_control.screen_action",
    },
    "fs": {
        "computer_control.fs_action",
        "computer_control.read_file",
        "computer_control.write_file",
        "computer_control.list_files",
        "computer_control.delete_file",
        "self_evolve.evolve_create_task",
        "self_evolve.evolve_collect_context",
        "self_evolve.evolve_apply_patch",
    },
    "runtime": {
        "computer_control.process_action",
        "computer_control.execute_command",
        "self_evolve.evolve_validate",
        "moirai.*",
    },
    "network": {
        "websearch.search",
        "websearch.quick_answer",
        "websearch.news_search",
    },
    "memory": {
        "memory.*",
    },
}

TOOLS_POLICY_PROFILES: Dict[str, Set[str]] = {
    # Conservative profile for general Q&A and low-risk operations.
    "minimal": {
        "websearch.search",
        "websearch.quick_answer",
        "websearch.news_search",
        "computer_control.read_file",
        "computer_control.list_files",
        "self_evolve.evolve_collect_context",
        "memory.*",
    },
    # Practical default for coding and local agent operations.
    "coding": {
        "group:network",
        "group:fs",
        "group:runtime",
        "computer_control.browser_action",
        "computer_control.screen_action",
    },
    # Broad capability surface for agentic workflows.
    "full": {
        "group:browser",
        "group:fs",
        "group:runtime",
        "group:network",
        "group:memory",
        "*",
    },
}


@dataclass
class ToolPolicyDecision:
    allowed: bool
    reason: str
    effective: Dict[str, Any]


class ToolPolicyEngine:
    """Resolve and enforce per-user tool policy with profile/allow/deny semantics."""

    def __init__(self):
        self.default_profile = "coding"

    def resolve_effective_policy(
        self,
        user_config: Optional[Dict[str, Any]],
        *,
        provider_id: str = "default",
    ) -> Dict[str, Any]:
        tools_cfg = {}
        if isinstance(user_config, dict):
            maybe = user_config.get("tools")
            if isinstance(maybe, dict):
                tools_cfg = maybe

        profile = str(tools_cfg.get("profile") or self.default_profile).strip().lower()
        if profile not in TOOLS_POLICY_PROFILES:
            profile = self.default_profile

        allow = self._to_set(tools_cfg.get("allow"))
        deny = self._to_set(tools_cfg.get("deny"))

        by_provider = tools_cfg.get("byProvider")
        if not isinstance(by_provider, dict):
            by_provider = tools_cfg.get("by_provider") if isinstance(tools_cfg.get("by_provider"), dict) else {}

        provider_cfg = by_provider.get(provider_id) if isinstance(by_provider, dict) else None
        if isinstance(provider_cfg, dict):
            profile = str(provider_cfg.get("profile") or profile).strip().lower() or profile
            if profile not in TOOLS_POLICY_PROFILES:
                profile = self.default_profile
            allow |= self._to_set(provider_cfg.get("allow"))
            deny |= self._to_set(provider_cfg.get("deny"))

        return {
            "profile": profile,
            "allow": allow,
            "deny": deny,
        }

    def check(
        self,
        *,
        service_name: str,
        tool_name: str,
        user_config: Optional[Dict[str, Any]],
        provider_id: str = "default",
    ) -> ToolPolicyDecision:
        effective = self.resolve_effective_policy(user_config, provider_id=provider_id)
        profile_allow = self._resolve_refs(TOOLS_POLICY_PROFILES.get(effective["profile"], set()))
        profile_deny = self._resolve_refs(effective["deny"])
        custom_allow = self._resolve_refs(effective["allow"])

        if custom_allow:
            allowed_set = set(custom_allow)
            allowed_set.update(profile_allow)
        else:
            allowed_set = set(profile_allow)

        denied_set = set(profile_deny)

        full_name = f"{service_name}.{tool_name}"
        names = {
            service_name,
            tool_name,
            full_name,
        }

        if self._matches_any(names, denied_set):
            return ToolPolicyDecision(False, f"blocked by deny policy: {full_name}", effective)

        if not allowed_set:
            return ToolPolicyDecision(True, "no allow policy configured", effective)

        if self._matches_any(names, allowed_set):
            return ToolPolicyDecision(True, f"allowed by profile '{effective['profile']}'", effective)

        return ToolPolicyDecision(False, f"not in allow policy: {full_name}", effective)

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

    def _resolve_refs(self, refs: Set[str]) -> Set[str]:
        out: Set[str] = set()
        for ref in refs:
            if ref.startswith("group:"):
                group_name = ref.split(":", 1)[1]
                out.update(TOOLS_GROUPS.get(group_name, set()))
            else:
                out.add(ref)
        return out

    @staticmethod
    def _matches_any(names: Set[str], rules: Set[str]) -> bool:
        if "*" in rules:
            return True
        for rule in rules:
            if not rule:
                continue
            for name in names:
                if fnmatch(name, rule):
                    return True
        return False
