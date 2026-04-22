from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from skills import build_default_skill_registry

from gateway.workflow_models import WorkflowDefinition, WorkflowStep
from ..dispatcher import get_gateway_server
from ..user_file_store import user_file_store
from ..user_manager import user_manager
from .auth import get_current_user_id


router = APIRouter()


class TemplateApplyRequest(BaseModel):
    template_id: str
    enable: bool = True
    activate: bool = True
    start_workflow: bool = False
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None


class PersonalExportRequest(BaseModel):
    include_messages: bool = True
    include_memory: bool = True
    include_files: bool = True
    include_file_content: bool = False


class PersonalImportRequest(BaseModel):
    bundle: Dict[str, Any]
    merge: bool = True
    restore_config: bool = True
    restore_sessions: bool = True
    restore_memory: bool = True
    restore_files: bool = True


def _require_runtime():
    gateway_server = get_gateway_server()
    config_service = getattr(gateway_server, "config_service", None)
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return gateway_server, config_service


def _build_workflow_template(template_id: str, *, user_id: str) -> Optional[WorkflowDefinition]:
    tid = str(template_id or "").strip()
    if tid == "workflow:personal.review":
        steps = [
            WorkflowStep(
                step_id="step_1_reason",
                step_type="reasoning_step",
                name="Review objective",
                description="Reason about current personal goals and blockers.",
                depends_on=[],
                inputs={"goal": "Summarize current priorities and blockers"},
            ),
            WorkflowStep(
                step_id="step_2_memory",
                step_type="memory_step",
                name="Persist summary",
                description="Store workflow summary into memory.",
                depends_on=["step_1_reason"],
                inputs={"summary": "Weekly personal progress review and next actions."},
            ),
            WorkflowStep(
                step_id="step_3_artifact",
                step_type="artifact_step",
                name="Write plan artifact",
                description="Write execution plan artifact.",
                depends_on=["step_2_memory"],
                inputs={"path": "workflows/personal_review.md", "content": "# Personal Review\n\n- Goals\n- Blockers\n- Next actions\n"},
            ),
        ]
        return WorkflowDefinition(
            workflow_id="tpl.personal.review",
            workflow_type="linear",
            name="Personal Review Template",
            description="Review goals, persist memory summary, and emit an artifact.",
            owner_user_id=user_id,
            steps=steps,
        )
    if tid == "workflow:file.ingest":
        steps = [
            WorkflowStep(
                step_id="step_1_reason",
                step_type="reasoning_step",
                name="Analyze uploaded files",
                description="Reason about recently uploaded files and extract useful tasks.",
                depends_on=[],
                inputs={"goal": "Read uploaded files and identify actionable tasks"},
            ),
            WorkflowStep(
                step_id="step_2_summary",
                step_type="summary_step",
                name="Summarize",
                description="Summarize extracted actions.",
                depends_on=["step_1_reason"],
                inputs={"summary": "File ingest digest with key actions and risks."},
            ),
        ]
        return WorkflowDefinition(
            workflow_id="tpl.file.ingest",
            workflow_type="linear",
            name="File Ingest Digest Template",
            description="Analyze uploaded files and produce concise action digest.",
            owner_user_id=user_id,
            steps=steps,
        )
    return None


@router.get("/personal/templates/catalog")
async def get_personal_template_catalog(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    _gateway_server, config_service = _require_runtime()
    registry = build_default_skill_registry()
    merged = config_service.get_merged_config(user_id)

    skills_templates: List[Dict[str, Any]] = []
    active_skill = str(((merged.get("skills") or {}).get("active")) or "")
    for spec in registry.list_skills(enabled_only=False):
        disabled = set(str(x) for x in (((merged.get("skills") or {}).get("disabled")) or []))
        enabled = spec.skill_id not in disabled
        skills_templates.append(
            {
                "template_id": f"skill:{spec.skill_id}",
                "kind": "skill",
                "name": spec.name,
                "description": spec.description,
                "enabled": bool(enabled),
                "active": spec.skill_id == active_skill,
                "source": "official",
                "ecosystem_ready": True,
            }
        )

    workflow_templates = [
        {
            "template_id": "workflow:personal.review",
            "kind": "workflow",
            "name": "Personal Review",
            "description": "Review goals and blockers, persist summary, write artifact.",
            "source": "official",
            "ecosystem_ready": True,
        },
        {
            "template_id": "workflow:file.ingest",
            "kind": "workflow",
            "name": "File Ingest Digest",
            "description": "Analyze uploaded files and produce digest actions.",
            "source": "official",
            "ecosystem_ready": True,
        },
    ]

    return {
        "status": "success",
        "user_id": user_id,
        "templates": skills_templates + workflow_templates,
        "counts": {
            "skills": len(skills_templates),
            "workflows": len(workflow_templates),
            "total": len(skills_templates) + len(workflow_templates),
        },
        "notice": "Templates are first-class capability packs and can evolve to open ecosystem distribution.",
    }


@router.post("/personal/templates/apply")
async def apply_personal_template(
    request: TemplateApplyRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, config_service = _require_runtime()
    template_id = str(request.template_id or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id is required")

    if template_id.startswith("skill:"):
        skill_id = template_id.split(":", 1)[1]
        registry = build_default_skill_registry()
        spec = registry.get_skill(skill_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="skill template not found")
        updates: Dict[str, Any] = {
            "skills": {"overrides": {skill_id: {"enabled": bool(request.enable)}}},
            "plugins": {skill_id: {"enabled": bool(request.enable), "config": {}}},
        }
        if request.activate and request.enable:
            updates["skills"]["active"] = skill_id
        result = await config_service.update_user_config(user_id, updates, validate=False)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "failed to apply skill template"))
        return {
            "status": "success",
            "template_id": template_id,
            "kind": "skill",
            "skill_id": skill_id,
            "enabled": bool(request.enable),
            "active": bool(request.activate and request.enable),
        }

    if template_id.startswith("workflow:"):
        workflow_engine = getattr(gateway_server, "workflow_engine", None)
        if workflow_engine is None:
            raise HTTPException(status_code=503, detail="Workflow engine not initialized")
        definition = _build_workflow_template(template_id, user_id=user_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        workflow_engine.define_workflow(definition)
        run_payload: Dict[str, Any] = {}
        if request.start_workflow:
            run = await workflow_engine.start_workflow_async(
                workflow_id=definition.workflow_id,
                session_id=str(request.session_id or "default_session"),
                user_id=user_id,
                workspace_id=str(request.workspace_id or request.session_id or "default_workspace"),
                run_context={"source": "template.apply"},
            )
            run_payload = {"run": run.model_dump()}
        return {
            "status": "success",
            "template_id": template_id,
            "kind": "workflow",
            "workflow": {
                "workflow_id": definition.workflow_id,
                "name": definition.name,
                "step_count": len(definition.steps),
            },
            **run_payload,
        }

    raise HTTPException(status_code=400, detail="unsupported template_id")


@router.get("/personal/workflow/runs")
async def list_personal_workflow_runs(
    status: str = "",
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, _config_service = _require_runtime()
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow engine not initialized")
    rows = workflow_engine.list_runs(user_id=user_id, limit=max(1, min(int(limit), 200)))
    status_filter = str(status or "").strip().lower()
    if status_filter:
        rows = [row for row in rows if str(row.get("status") or "").lower() == status_filter]
    return {
        "status": "success",
        "user_id": user_id,
        "runs": rows,
        "total": len(rows),
    }


@router.get("/personal/workflow/recovery")
async def list_personal_workflow_recovery(
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, _config_service = _require_runtime()
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    if workflow_engine is None:
        raise HTTPException(status_code=503, detail="Workflow engine not initialized")
    rows = workflow_engine.list_runs(user_id=user_id, limit=max(1, min(int(limit), 200)))
    recoverable: List[Dict[str, Any]] = []
    for row in rows:
        st = str(row.get("status") or "").lower()
        if st not in {"paused", "failed", "waiting_human"}:
            continue
        item = dict(row)
        if st in {"paused", "waiting_human"}:
            item["recommended_action"] = "resume"
        else:
            item["recommended_action"] = "retry"
            item["retry_step_id"] = str(row.get("current_step_id") or "")
        recoverable.append(item)
    return {
        "status": "success",
        "user_id": user_id,
        "runs": recoverable,
        "total": len(recoverable),
    }


@router.post("/personal/export")
async def export_personal_bundle(
    request: PersonalExportRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, config_service = _require_runtime()
    message_manager = getattr(gateway_server, "message_manager", None)
    if message_manager is None:
        raise HTTPException(status_code=503, detail="Message manager not initialized")

    raw_user_config = user_manager.get_user_config(user_id)
    sessions = message_manager.export_user_sessions(user_id=user_id, include_messages=bool(request.include_messages))
    files_payload = (
        user_file_store.export_user_bundle(
            user_id=user_id,
            include_content=bool(request.include_file_content),
            limit=5000,
        )
        if request.include_files
        else {"items": [], "stats": {"total_files": 0, "total_bytes": 0}, "include_content": False}
    )

    memory_payload: Dict[str, Any] = {"included": False, "mef": {}}
    memory_service = getattr(gateway_server, "memory_service", None)
    if request.include_memory and memory_service and getattr(memory_service, "memory_adapter", None):
        try:
            mef = memory_service.memory_adapter.export_mef(user_id=user_id)
            memory_payload = {"included": True, "mef": mef}
        except Exception as e:
            memory_payload = {"included": True, "mef": {}, "error": str(e)}

    effective_config = config_service.get_merged_config(user_id)
    bundle = {
        "bundle_version": "personal.v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "user_id": user_id,
        "payload": {
            "config": {
                "user_config": raw_user_config,
                "effective_config": effective_config,
            },
            "sessions": sessions,
            "files": files_payload,
            "memory": memory_payload,
        },
    }
    return {"status": "success", "bundle": bundle}


@router.post("/personal/import")
async def import_personal_bundle(
    request: PersonalImportRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, config_service = _require_runtime()
    message_manager = getattr(gateway_server, "message_manager", None)
    if message_manager is None:
        raise HTTPException(status_code=503, detail="Message manager not initialized")

    bundle = request.bundle if isinstance(request.bundle, dict) else {}
    payload = bundle.get("payload") if isinstance(bundle.get("payload"), dict) else {}
    result: Dict[str, Any] = {"status": "success", "user_id": user_id, "applied": {}}

    if request.restore_config:
        cfg = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        user_cfg = cfg.get("user_config") if isinstance(cfg.get("user_config"), dict) else {}
        if user_cfg:
            updated = await config_service.update_user_config(user_id, user_cfg, validate=False)
            result["applied"]["config"] = {"success": bool(updated.get("success")), "message": updated.get("message")}
        else:
            result["applied"]["config"] = {"success": False, "message": "no user_config in bundle"}

    if request.restore_sessions:
        rows = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
        result["applied"]["sessions"] = message_manager.import_user_sessions(
            user_id=user_id,
            sessions=rows,
            merge=bool(request.merge),
        )

    if request.restore_files:
        files_bundle = payload.get("files") if isinstance(payload.get("files"), dict) else {}
        result["applied"]["files"] = user_file_store.import_user_bundle(
            user_id=user_id,
            bundle=files_bundle,
            merge=bool(request.merge),
        )

    if request.restore_memory:
        memory_bundle = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
        mef = memory_bundle.get("mef") if isinstance(memory_bundle.get("mef"), dict) else {}
        memory_service = getattr(gateway_server, "memory_service", None)
        adapter = getattr(memory_service, "memory_adapter", None) if memory_service else None
        if adapter and mef:
            try:
                out = adapter.import_mef(mef, merge=bool(request.merge))
                result["applied"]["memory"] = out
            except Exception as e:
                result["applied"]["memory"] = {"ok": False, "reason": str(e)}
        else:
            result["applied"]["memory"] = {"ok": False, "reason": "memory adapter unavailable or mef missing"}

    return result
