from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .schema import SkillEvaluationCase, SkillExample, SkillSpec


class SkillRegistry:
    def __init__(self, packs_root: Optional[str] = None) -> None:
        self.packs_root = packs_root or os.path.join(os.getcwd(), "skills", "packs", "official")
        self._skills: Dict[str, SkillSpec] = {}

    @staticmethod
    def _read_text(path: str, default: str = "") -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return default

    @staticmethod
    def _read_struct(path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except FileNotFoundError:
            return default
        if not raw:
            return default
        raw = raw.lstrip("\ufeff")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def register(self, spec: SkillSpec) -> SkillSpec:
        self._skills[str(spec.skill_id)] = spec
        return spec

    def get_skill(self, skill_id: Optional[str]) -> Optional[SkillSpec]:
        if not skill_id:
            return None
        return self._skills.get(str(skill_id))

    def list_skills(self, *, enabled_only: bool = False) -> List[SkillSpec]:
        rows = list(self._skills.values())
        if enabled_only:
            rows = [s for s in rows if s.enabled]
        return sorted(rows, key=lambda s: s.skill_id)

    def list_skills_for_user(
        self,
        *,
        user_config: Optional[Dict[str, Any]],
        model_invocable_only: bool = False,
    ) -> List[SkillSpec]:
        rows = [
            s
            for s in self.list_skills(enabled_only=True)
            if self._is_skill_enabled_for_user(s.skill_id, user_config=user_config)
        ]
        if model_invocable_only:
            rows = [s for s in rows if bool(s.model_invocable)]
        return sorted(rows, key=lambda s: s.skill_id)

    def build_listing_prompt(
        self,
        *,
        user_config: Optional[Dict[str, Any]],
        max_chars: int = 8000,
        per_skill_desc_limit: int = 250,
    ) -> Dict[str, Any]:
        max_chars = int(max_chars or 8000)
        if max_chars <= 256:
            max_chars = 256
        per_skill_desc_limit = int(per_skill_desc_limit or 250)
        if per_skill_desc_limit <= 32:
            per_skill_desc_limit = 32

        lines: List[str] = [
            "Skills are available via tool `skill.run`.",
            "Use `skill.run` only when the task clearly matches a listed skill.",
            "Do not assume skill internals before calling `skill.run`.",
            "",
            "Available skills:",
        ]
        items: List[Dict[str, Any]] = []
        for spec in self.list_skills_for_user(user_config=user_config, model_invocable_only=True):
            desc = str(spec.when_to_use or spec.description or "").strip()
            if len(desc) > per_skill_desc_limit:
                desc = f"{desc[:per_skill_desc_limit].rstrip()}..."
            row = f"- {spec.skill_id}: {desc}" if desc else f"- {spec.skill_id}"
            projected = "\n".join(lines + [row])
            if len(projected) > max_chars:
                break
            lines.append(row)
            items.append(
                {
                    "skill_id": spec.skill_id,
                    "name": spec.name,
                    "description": spec.description,
                    "when_to_use": spec.when_to_use,
                    "category": spec.category,
                    "version": spec.version,
                    "model_invocable": bool(spec.model_invocable),
                    "execution_context": spec.execution_context,
                }
            )

        return {
            "listing_prompt": "\n".join(lines).strip(),
            "skills": items,
            "count": len(items),
            "max_chars": max_chars,
            "per_skill_desc_limit": per_skill_desc_limit,
        }

    def load_official_packs(self, *, clear_existing: bool = True) -> int:
        if clear_existing:
            self._skills.clear()

        if not os.path.isdir(self.packs_root):
            return 0

        loaded = 0
        for entry in sorted(os.listdir(self.packs_root)):
            pack_dir = os.path.join(self.packs_root, entry)
            if not os.path.isdir(pack_dir):
                continue
            spec = self._load_pack(pack_dir)
            if spec is None:
                continue
            self.register(spec)
            loaded += 1
        return loaded

    def _load_pack(self, pack_dir: str) -> Optional[SkillSpec]:
        manifest = self._read_struct(os.path.join(pack_dir, "skill.yaml"), default={})
        if not isinstance(manifest, dict):
            return None

        system_instruction = self._read_text(
            os.path.join(pack_dir, "system_instruction.md"),
            default=str(manifest.get("system_instruction") or ""),
        )

        tool_allowlist_raw = self._read_struct(
            os.path.join(pack_dir, "tool_allowlist.yaml"),
            default=manifest.get("tool_allowlist") or [],
        )
        if isinstance(tool_allowlist_raw, dict):
            tool_allowlist = tool_allowlist_raw.get("tools") or []
        elif isinstance(tool_allowlist_raw, list):
            tool_allowlist = tool_allowlist_raw
        else:
            tool_allowlist = []

        manifest_allowed = manifest.get("allowed_tools") if isinstance(manifest.get("allowed_tools"), list) else []
        merged_allowed = list(tool_allowlist) + list(manifest_allowed)
        allowed_tools = [str(x).strip() for x in merged_allowed if str(x).strip()]
        # keep deterministic order
        dedup_allowed: List[str] = []
        seen = set()
        for t in allowed_tools:
            if t in seen:
                continue
            seen.add(t)
            dedup_allowed.append(t)

        examples_raw = self._read_struct(
            os.path.join(pack_dir, "examples.json"),
            default=manifest.get("examples") or [],
        )
        if not isinstance(examples_raw, list):
            examples_raw = []

        eval_raw = self._read_struct(
            os.path.join(pack_dir, "evaluation_cases.json"),
            default=manifest.get("evaluation_cases") or [],
        )
        if not isinstance(eval_raw, list):
            eval_raw = []

        raw_context = str(manifest.get("execution_context") or manifest.get("context") or "inline").strip().lower()
        execution_context = raw_context if raw_context in {"inline", "fork"} else "inline"

        if "model_invocable" in manifest:
            model_invocable = bool(manifest.get("model_invocable"))
        else:
            model_invocable = not bool(manifest.get("disable_model_invocation", False))

        try:
            examples = [SkillExample(**item) for item in examples_raw if isinstance(item, dict)]
            evaluation_cases = [
                SkillEvaluationCase(**item)
                for item in eval_raw
                if isinstance(item, dict)
            ]
            return SkillSpec(
                skill_id=str(manifest.get("skill_id") or os.path.basename(pack_dir)),
                name=str(manifest.get("name") or os.path.basename(pack_dir)),
                description=str(manifest.get("description") or ""),
                when_to_use=str(manifest.get("when_to_use") or ""),
                category=str(manifest.get("category") or "general"),
                model_invocable=bool(model_invocable),
                execution_context=execution_context,
                system_instruction=system_instruction,
                allowed_tools=dedup_allowed,
                tool_allowlist=dedup_allowed,
                model_override=str(manifest.get("model_override") or ""),
                effort_override=str(manifest.get("effort_override") or ""),
                permission_profile=str(manifest.get("permission_profile") or "default"),
                prompt_block_policy=(manifest.get("prompt_block_policy") or {}),
                default_mode=str(manifest.get("default_mode") or "fast"),
                examples=examples,
                evaluation_cases=evaluation_cases,
                version=str(manifest.get("version") or "0.1.0"),
                enabled=bool(manifest.get("enabled", True)),
                source="official",
                pack_path=pack_dir,
            )
        except Exception:
            return None

    def resolve_skill_for_user(
        self,
        *,
        requested_skill: Optional[str],
        user_config: Optional[Dict[str, Any]],
    ) -> Optional[SkillSpec]:
        if not requested_skill:
            requested_skill = self._extract_active_skill(user_config)
        spec = self.get_skill(requested_skill)
        if spec is None:
            return None
        if not self._is_skill_enabled_for_user(spec.skill_id, user_config=user_config):
            return None
        return spec

    @staticmethod
    def _extract_active_skill(user_config: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(user_config, dict):
            return None
        skills_cfg = user_config.get("skills")
        if isinstance(skills_cfg, dict):
            active = skills_cfg.get("active")
            if isinstance(active, str) and active.strip():
                return active.strip()
        return None

    @staticmethod
    def _is_skill_enabled_for_user(
        skill_id: str,
        *,
        user_config: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(user_config, dict):
            return True

        skills_cfg = user_config.get("skills")
        if isinstance(skills_cfg, dict):
            if skill_id in set(str(x) for x in (skills_cfg.get("disabled") or [])):
                return False
            enabled = skills_cfg.get("enabled")
            if isinstance(enabled, list) and enabled:
                return skill_id in set(str(x) for x in enabled)
            overrides = skills_cfg.get("overrides")
            if isinstance(overrides, dict) and isinstance(overrides.get(skill_id), dict):
                row = overrides.get(skill_id) or {}
                if "enabled" in row:
                    return bool(row.get("enabled"))

        plugins_cfg = user_config.get("plugins")
        if isinstance(plugins_cfg, dict) and isinstance(plugins_cfg.get(skill_id), dict):
            return bool(plugins_cfg.get(skill_id, {}).get("enabled", True))

        return True


_DEFAULT_REGISTRY: Optional[SkillRegistry] = None


def build_default_skill_registry() -> SkillRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        reg = SkillRegistry()
        reg.load_official_packs(clear_existing=True)
        _DEFAULT_REGISTRY = reg
    return _DEFAULT_REGISTRY
