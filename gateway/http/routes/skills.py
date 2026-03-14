from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from skills import build_default_skill_registry

from .auth import get_current_user_id
from ..dispatcher import get_gateway_server


router = APIRouter()


class SkillInstallRequest(BaseModel):
    skill_id: str
    enabled: bool = True


class SkillActivateRequest(BaseModel):
    skill_id: Optional[str] = None


def _get_config_service_or_503():
    gateway_server = get_gateway_server()
    config_service = getattr(gateway_server, "config_service", None)
    if not config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return config_service


def _get_skill_registry():
    gateway_server = get_gateway_server()
    registry = getattr(gateway_server, "skill_registry", None)
    if registry is None:
        registry = build_default_skill_registry()
        setattr(gateway_server, "skill_registry", registry)
    return registry


def _skill_enabled_for_user(skill_id: str, merged_config: Dict[str, Any]) -> bool:
    skills_cfg = merged_config.get("skills") if isinstance(merged_config, dict) else {}
    if isinstance(skills_cfg, dict):
        disabled = {str(x) for x in (skills_cfg.get("disabled") or [])}
        if skill_id in disabled:
            return False
        overrides = skills_cfg.get("overrides") or {}
        if isinstance(overrides, dict) and isinstance(overrides.get(skill_id), dict):
            row = overrides.get(skill_id) or {}
            if "enabled" in row:
                return bool(row.get("enabled"))

    plugins_cfg = merged_config.get("plugins") if isinstance(merged_config, dict) else {}
    if isinstance(plugins_cfg, dict) and isinstance(plugins_cfg.get(skill_id), dict):
        return bool(plugins_cfg.get(skill_id, {}).get("enabled", True))

    return True


def _to_catalog_item(spec, *, enabled: bool) -> Dict[str, Any]:
    return {
        "id": spec.skill_id,
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "version": spec.version,
        "source": spec.source,
        "enabled": bool(enabled and spec.enabled),
        "default_mode": spec.default_mode,
        "tool_allowlist": list(spec.tool_allowlist),
        "example_count": len(spec.examples),
        "evaluation_case_count": len(spec.evaluation_cases),
    }


@router.get("/skills/catalog")
async def get_skills_catalog(user_id: str = Depends(get_current_user_id)):
    config_service = _get_config_service_or_503()
    registry = _get_skill_registry()

    merged = config_service.get_merged_config(user_id)
    active_skill = ((merged.get("skills") or {}).get("active") if isinstance(merged, dict) else None)

    rows = []
    for spec in registry.list_skills(enabled_only=False):
        rows.append(
            _to_catalog_item(
                spec,
                enabled=_skill_enabled_for_user(spec.skill_id, merged),
            )
        )

    return {
        "status": "success",
        "user_id": user_id,
        "active_skill": active_skill,
        "total": len(rows),
        "skills": rows,
    }


@router.get("/skills/{skill_id}")
async def get_skill_detail(skill_id: str, user_id: str = Depends(get_current_user_id)):
    config_service = _get_config_service_or_503()
    registry = _get_skill_registry()

    merged = config_service.get_merged_config(user_id)
    spec = registry.get_skill(skill_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="skill not found")

    enabled = _skill_enabled_for_user(skill_id, merged)
    item = _to_catalog_item(spec, enabled=enabled)
    item["system_instruction"] = spec.system_instruction
    item["prompt_block_policy"] = dict(spec.prompt_block_policy or {})
    item["examples"] = [example.model_dump() for example in spec.examples]
    item["evaluation_cases"] = [case.model_dump() for case in spec.evaluation_cases]

    return {
        "status": "success",
        "user_id": user_id,
        "skill": item,
    }


@router.post("/skills/install")
async def install_skill(
    request: SkillInstallRequest,
    user_id: str = Depends(get_current_user_id),
):
    config_service = _get_config_service_or_503()
    registry = _get_skill_registry()

    spec = registry.get_skill(request.skill_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="skill not found in official catalog")

    result = await config_service.update_user_config(
        user_id,
        {
            "skills": {
                "overrides": {
                    request.skill_id: {
                        "enabled": bool(request.enabled),
                    }
                }
            },
            # Keep backward-compatible plugin switch for existing logic.
            "plugins": {
                request.skill_id: {
                    "enabled": bool(request.enabled),
                    "config": {},
                }
            },
        },
        validate=False,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "failed to install skill"))

    return {
        "status": "success",
        "user_id": user_id,
        "skill_id": request.skill_id,
        "enabled": bool(request.enabled),
        "message": "skill state updated in user config",
    }


@router.post("/skills/activate")
async def activate_skill(
    request: SkillActivateRequest,
    user_id: str = Depends(get_current_user_id),
):
    config_service = _get_config_service_or_503()
    registry = _get_skill_registry()

    if request.skill_id:
        spec = registry.get_skill(request.skill_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="skill not found in official catalog")

    result = await config_service.update_user_config(
        user_id,
        {
            "skills": {
                "active": request.skill_id,
            }
        },
        validate=False,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "failed to activate skill"))

    return {
        "status": "success",
        "user_id": user_id,
        "active_skill": request.skill_id,
    }
