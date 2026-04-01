from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.tool_service import ToolInvocationContext
from skills import build_default_skill_registry


class SkillRunTool:
    tool_id = "skill.run"
    name = "skill.run"
    description = "Load full instructions and runtime metadata for one skill on demand."
    official = True
    official_domain = "skill"

    def __init__(self, *, gateway_server: Any = None) -> None:
        self.gateway_server = gateway_server

    def _resolve_registry(self):
        if self.gateway_server is not None:
            registry = getattr(self.gateway_server, "skill_registry", None)
            if registry is not None:
                return registry
        return build_default_skill_registry()

    def _resolve_user_config(self, user_id: Optional[str]) -> Dict[str, Any]:
        if self.gateway_server is None:
            return {}
        config_service = getattr(self.gateway_server, "config_service", None)
        if config_service is None or not user_id:
            return {}
        try:
            cfg = config_service.get_merged_config(str(user_id))
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        payload = dict(args or {})
        skill_id = str(payload.get("skill_id") or "").strip()
        include_examples = bool(payload.get("include_examples", False))
        include_evaluation_cases = bool(payload.get("include_evaluation_cases", False))
        allow_manual = bool(payload.get("allow_manual", False))

        registry = self._resolve_registry()
        user_id = str(getattr(ctx, "user_id", "") or "").strip() if ctx is not None else ""
        user_config = self._resolve_user_config(user_id)

        if not skill_id and hasattr(registry, "_extract_active_skill"):
            skill_id = str(registry._extract_active_skill(user_config) or "").strip()

        if not skill_id:
            return {
                "ok": False,
                "reason": "missing_skill_id",
                "message": "skill_id is required (or configure an active skill).",
            }

        spec = registry.resolve_skill_for_user(requested_skill=skill_id, user_config=user_config)
        if spec is None:
            return {
                "ok": False,
                "reason": "skill_not_found_or_disabled",
                "skill_id": skill_id,
            }

        if not bool(spec.model_invocable) and not allow_manual:
            return {
                "ok": False,
                "reason": "model_invocation_disabled",
                "skill_id": skill_id,
                "message": "This skill disables model invocation. Re-run with allow_manual=true for explicit/manual usage.",
            }

        result: Dict[str, Any] = {
            "ok": True,
            "skill": {
                "skill_id": spec.skill_id,
                "name": spec.name,
                "description": spec.description,
                "when_to_use": spec.when_to_use,
                "category": spec.category,
                "version": spec.version,
                "default_mode": spec.default_mode,
                "model_invocable": bool(spec.model_invocable),
                "execution_context": spec.execution_context,
                "allowed_tools": list(spec.allowed_tools or spec.tool_allowlist),
                "model_override": spec.model_override,
                "effort_override": spec.effort_override,
                "permission_profile": spec.permission_profile,
                "prompt_block_policy": dict(spec.prompt_block_policy or {}),
            },
            "instruction": str(spec.system_instruction or "").strip(),
        }
        if include_examples:
            result["examples"] = [item.model_dump() for item in spec.examples]
        if include_evaluation_cases:
            result["evaluation_cases"] = [item.model_dump() for item in spec.evaluation_cases]
        return result
