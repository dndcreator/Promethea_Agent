from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from skills import build_default_skill_registry

from gateway.workflow_models import WorkflowDefinition, WorkflowStep
from ..dispatcher import get_gateway_server
from ..user_file_store import user_file_store
from ..user_manager import user_manager
from ...avatar_service import avatar_service
from ..personal_workspace_archive import build_archive, read_archive, rebind_user_scope
from .auth import get_current_user_id
from .projects import get_project_store
from ..project_store import ProjectStore


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


def _portable_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep user preference records, never deployment credentials or endpoints."""
    forbidden = {"api_key", "password", "token", "secret", "base_url", "uri", "url", "model"}
    if isinstance(raw, list):
        return [_portable_config(item) for item in raw]  # type: ignore[arg-type]
    if not isinstance(raw, dict):
        return raw  # type: ignore[return-value]
    clean: Dict[str, Any] = {}
    for key, value in raw.items():
        if str(key).lower() in forbidden:
            continue
        clean[str(key)] = _portable_config(value) if isinstance(value, (dict, list)) else value
    return clean


def _build_workspace_payload(*, gateway_server: Any, user_id: str) -> Dict[str, Any]:
    message_manager = getattr(gateway_server, "message_manager", None)
    if message_manager is None:
        raise HTTPException(status_code=503, detail="Message manager not initialized")
    memory_service = getattr(gateway_server, "memory_service", None)
    adapter = getattr(memory_service, "memory_adapter", None) if memory_service else None
    mef = adapter.export_mef(user_id=user_id) if adapter else {}
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    task_service = getattr(gateway_server, "task_service", None)
    reasoning_service = getattr(gateway_server, "reasoning_service", None)
    learning = getattr(getattr(reasoning_service, "template_memory", None), "learning", None)
    from computer.canvas_document import export_canvas_library
    workspace_service = getattr(gateway_server, "workspace_service", None)
    library = workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id="_canvas_library") if workspace_service else None
    return {
        "schema_version": 2,
        "config": _portable_config(user_manager.get_user_config(user_id)),
        "sessions": message_manager.export_user_sessions(user_id=user_id, include_messages=True),
        "projects": get_project_store().list(user_id),
        "memory": {"mef": mef},
        "memory_audit": memory_service.export_user_audit_records(user_id=user_id) if memory_service else {},
        "files": user_file_store.export_user_bundle(user_id=user_id, include_content=True, limit=5000),
        "avatar": avatar_service.export_user_bundle(user_id=user_id),
        "workflows": workflow_engine.export_user_state(user_id=user_id) if workflow_engine else {},
        "tasks": task_service.export_user_state(user_id=user_id) if task_service else {},
        "ambient": gateway_server.ambient_service.store.export_user_state(user_id) if getattr(gateway_server, "ambient_service", None) else {},
        "self_model": gateway_server.self_model_service.state.export_user_state(user_id) if getattr(gateway_server, "self_model_service", None) else {},
        "reasoning_history": reasoning_service.tree_history.export_user_history(user_id=user_id) if reasoning_service else [],
        "moirai_learning": learning.export_user_state(user_id) if learning else {},
        "canvas_apps": export_canvas_library(Path(library.root_path)) if library else [],
    }


async def _restore_workspace_payload(*, gateway_server: Any, config_service: Any, user_id: str, payload: Dict[str, Any], merge: bool) -> Dict[str, Any]:
    source_user_id = str(payload.get("source_user_id") or user_id)
    scoped = rebind_user_scope(payload, source_user_id=source_user_id, target_user_id=user_id)
    try:
        project_rows = ProjectStore.validate_records(scoped["projects"]) if "projects" in scoped else None
        if "ambient" in scoped:
            from gateway.ambient_state import AmbientControl
            for row in scoped["ambient"].get("situations", []):
                AmbientControl.model_validate({key: value for key, value in row.items() if key not in {"attention", "questions", "reflection", "feedback"}})
                if scoped["ambient"].get("version", 2) < 3:
                    from gateway.self_model_state import WorkingSituation
                    WorkingSituation(attention=row.get("attention", []), questions=row.get("questions", []), interpretation=row.get("reflection", ""), feedback=row.get("feedback", []))
        if scoped.get("self_model"):
            from gateway.self_model_state import WorkingSituation
            if scoped["self_model"].get("version") != 1:
                raise ValueError("unsupported self-model transfer version")
            WorkingSituation.model_validate(scoped["self_model"]["situation"])
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    message_manager = getattr(gateway_server, "message_manager", None)
    memory_service = getattr(gateway_server, "memory_service", None)
    adapter = getattr(memory_service, "memory_adapter", None) if memory_service else None
    workflow_engine = getattr(gateway_server, "workflow_engine", None)
    task_service = getattr(gateway_server, "task_service", None)
    reasoning_service = getattr(gateway_server, "reasoning_service", None)
    result: Dict[str, Any] = {"status": "success", "user_id": user_id, "mode": "merge" if merge else "replace", "applied": {}}
    self_model = getattr(gateway_server, "self_model_service", None)
    if self_model is not None and scoped.get("self_model"):
        self_model.state.import_user_state(user_id, scoped["self_model"], merge=merge)
        self_model.environment.purge(user_id)
        result["applied"]["self_model"] = {"success": True}
    ambient = getattr(gateway_server, "ambient_service", None)
    if ambient and "ambient" in scoped:
        for scene in list(ambient.store.scenes.values()):
            if scene.user_id == user_id and scene.settings.enabled:
                ambient.configure(user_id, None, scene.settings.model_copy(update={"enabled": False}))
        ambient.store.import_user_state(user_id, scoped["ambient"], merge=merge)
        result["applied"]["ambient"] = {"success": True, "enabled": False}
    config = scoped.get("config") if isinstance(scoped.get("config"), dict) else {}
    if config:
        updated = await config_service.update_user_config(user_id, config, validate=False)
        result["applied"]["config"] = {"success": bool(updated.get("success")), "message": updated.get("message")}
    sessions = scoped.get("sessions") if isinstance(scoped.get("sessions"), list) else []
    result["applied"]["sessions"] = (
        message_manager.import_user_sessions(user_id=user_id, sessions=sessions, merge=True)
        if merge else message_manager.replace_user_sessions(user_id=user_id, sessions=sessions)
    )
    if project_rows is not None:
        owned_ids = {
            str(row.get("session_id")) for row in sessions
            if isinstance(row, dict) and row.get("session_id")
            and message_manager.get_session(str(row["session_id"]), user_id=user_id) is not None
        }
        get_project_store().import_records(user_id, project_rows, merge=merge, owned_session_ids=owned_ids)
        result["applied"]["projects"] = {"count": len(project_rows)}
    elif not merge:
        get_project_store().clear_user(user_id)
    files = scoped.get("files") if isinstance(scoped.get("files"), dict) else {}
    if not merge:
        user_file_store.clear_user_bundle(user_id=user_id)
    result["applied"]["files"] = user_file_store.import_user_bundle(user_id=user_id, bundle=files, merge=merge)
    try:
        result["applied"]["avatar"] = avatar_service.import_user_bundle(user_id=user_id, bundle=scoped.get("avatar") or {})
    except Exception as exc:
        result["applied"]["avatar"] = {"ok": False, "reason": str(exc)}
    memory = scoped.get("memory") if isinstance(scoped.get("memory"), dict) else {}
    mef = memory.get("mef") if isinstance(memory.get("mef"), dict) else {}
    if adapter and mef:
        result["applied"]["memory"] = adapter.import_mef(mef, merge=True) if merge else adapter.replace_user_mef(mef, user_id=user_id)
    else:
        result["applied"]["memory"] = {"ok": False, "reason": "memory adapter unavailable or mef missing"}
    if memory_service:
        audit = scoped.get("memory_audit") if isinstance(scoped.get("memory_audit"), dict) else {}
        result["applied"]["memory_audit"] = memory_service.import_user_audit_records(user_id=user_id, payload=audit, merge=merge)
    workflows = scoped.get("workflows") if isinstance(scoped.get("workflows"), dict) else {}
    if workflow_engine:
        result["applied"]["workflows"] = workflow_engine.import_user_state(user_id=user_id, payload=workflows, merge=merge)
    tasks = scoped.get("tasks") if isinstance(scoped.get("tasks"), dict) else {}
    if task_service:
        result["applied"]["tasks"] = task_service.import_user_state(user_id=user_id, payload=tasks, merge=merge)
    if reasoning_service:
        result["applied"]["reasoning_history"] = reasoning_service.tree_history.import_user_history(user_id=user_id, rows=scoped.get("reasoning_history") or [], merge=merge)
        learning = getattr(getattr(reasoning_service, "template_memory", None), "learning", None)
        if learning is not None and "moirai_learning" in scoped:
            await learning.interrupt(user_id)
            learning.import_user_state(user_id, scoped["moirai_learning"], merge=merge)
            result["applied"]["moirai_learning"] = True
    if "canvas_apps" in scoped:
        from .canvas import restore_canvas_library
        if scoped["canvas_apps"] or getattr(gateway_server, "workspace_service", None):
            # App data is opaque content, not Runtime ownership metadata.
            result["applied"]["canvas_apps"] = await restore_canvas_library(user_id, payload["canvas_apps"], merge=merge)
    return result


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
            "projects": get_project_store().list(user_id),
            "files": files_payload,
            "memory": memory_payload,
        },
    }
    return {"status": "success", "bundle": bundle}


@router.post("/personal/workspace/archive")
async def export_personal_workspace_archive(
    user_id: str = Depends(get_current_user_id),
):
    gateway_server, _config_service = _require_runtime()
    archive = build_archive(
        user_id=user_id,
        payload=_build_workspace_payload(gateway_server=gateway_server, user_id=user_id),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        content=archive,
        media_type="application/vnd.promethea.workspace+zip",
        headers={"Content-Disposition": f'attachment; filename="promethea-workspace-{stamp}.promethea-workspace"'},
    )


@router.post("/personal/workspace/restore")
async def restore_personal_workspace_archive(
    archive: UploadFile = File(...),
    merge: bool = False,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server, config_service = _require_runtime()
    raw = await archive.read()
    try:
        manifest, payload = read_archive(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = dict(payload)
    payload["source_user_id"] = str(manifest.get("source_user_id") or "")
    result = await _restore_workspace_payload(
        gateway_server=gateway_server,
        config_service=config_service,
        user_id=user_id,
        payload=payload,
        merge=bool(merge),
    )
    result["archive"] = {"format": manifest.get("format"), "exported_at": manifest.get("exported_at")}
    return result


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
    try:
        project_rows = ProjectStore.validate_records(payload["projects"]) if request.restore_sessions and "projects" in payload else None
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
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
        if project_rows is not None:
            owned_ids = {str(row["session_id"]) for row in rows if isinstance(row, dict) and row.get("session_id") and message_manager.get_session(str(row["session_id"]), user_id=user_id) is not None}
            get_project_store().import_records(user_id, project_rows, merge=bool(request.merge), owned_session_ids=owned_ids)
            result["applied"]["projects"] = {"count": len(project_rows)}

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
