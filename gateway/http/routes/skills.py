from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.plugins.discovery import discover_promethea_plugins
from core.plugins.manifest import load_plugin_manifest

from .auth import get_current_user_id
from ..dispatcher import get_gateway_server


router = APIRouter()


class SkillInstallRequest(BaseModel):
    skill_id: str
    enabled: bool = True


def _get_config_service_or_503():
    gateway_server = get_gateway_server()
    config_service = getattr(gateway_server, "config_service", None)
    if not config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return config_service


def _discover_skills(workspace_dir: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cand in discover_promethea_plugins(workspace_dir, "extensions"):
        ok, manifest_path, manifest_or_error = load_plugin_manifest(cand.root_dir)
        if not ok:
            out.append(
                {
                    "id": os.path.basename(cand.root_dir),
                    "status": "invalid",
                    "error": str(manifest_or_error),
                    "source": cand.source,
                    "manifest_path": manifest_path,
                }
            )
            continue
        manifest = manifest_or_error
        out.append(
            {
                "id": manifest.id,
                "name": manifest.name,
                "kind": manifest.kind.value if manifest.kind else None,
                "description": manifest.description,
                "version": manifest.version,
                "status": "available",
                "source": cand.source,
                "manifest_path": manifest_path,
            }
        )
    return sorted(out, key=lambda x: str(x.get("id") or ""))


@router.get("/skills/catalog")
async def get_skills_catalog(user_id: str = Depends(get_current_user_id)):
    config_service = _get_config_service_or_503()
    merged = config_service.get_merged_config(user_id)
    plugins_cfg = (merged.get("plugins") or {}) if isinstance(merged, dict) else {}

    skills = _discover_skills(os.getcwd())
    for skill in skills:
        sid = skill.get("id")
        entry = plugins_cfg.get(sid) if isinstance(plugins_cfg, dict) else None
        if isinstance(entry, dict):
            skill["enabled"] = bool(entry.get("enabled", True))
        else:
            skill["enabled"] = True
    return {
        "status": "success",
        "user_id": user_id,
        "total": len(skills),
        "skills": skills,
    }


@router.post("/skills/install")
async def install_skill(
    request: SkillInstallRequest,
    user_id: str = Depends(get_current_user_id),
):
    config_service = _get_config_service_or_503()

    skills = _discover_skills(os.getcwd())
    available = {str(item.get("id")): item for item in skills if item.get("status") == "available"}
    if request.skill_id not in available:
        raise HTTPException(status_code=404, detail="skill not found in local catalog")

    result = await config_service.update_user_config(
        user_id,
        {
            "plugins": {
                request.skill_id: {
                    "enabled": bool(request.enabled),
                    "config": {},
                }
            }
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
