from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.http.routes import personal


@pytest.mark.asyncio
async def test_personal_template_catalog_contains_skills_and_workflows(monkeypatch):
    class _Registry:
        def list_skills(self, enabled_only=False):
            _ = enabled_only
            return [
                SimpleNamespace(skill_id="writing", name="Writing", description="Write clearly"),
                SimpleNamespace(skill_id="planner", name="Planner", description="Plan tasks"),
            ]

    class _Cfg:
        def get_merged_config(self, user_id):
            _ = user_id
            return {"skills": {"active": "writing", "disabled": ["planner"]}}

    monkeypatch.setattr(personal, "_require_runtime", lambda: (SimpleNamespace(), _Cfg()))
    monkeypatch.setattr(personal, "build_default_skill_registry", lambda: _Registry())

    out = await personal.get_personal_template_catalog(user_id="u1")
    assert out["status"] == "success"
    assert out["counts"]["skills"] == 2
    assert out["counts"]["workflows"] == 2
    assert out["counts"]["total"] == 4
    skills = [x for x in out["templates"] if x.get("kind") == "skill"]
    assert any(x["template_id"] == "skill:writing" and x["active"] is True for x in skills)
    assert any(x["template_id"] == "skill:planner" and x["enabled"] is False for x in skills)


@pytest.mark.asyncio
async def test_apply_personal_skill_template_updates_config(monkeypatch):
    captured = {}

    class _Registry:
        def get_skill(self, skill_id):
            if skill_id == "writing":
                return SimpleNamespace(skill_id="writing", name="Writing", description="Write clearly")
            return None

    class _Cfg:
        async def update_user_config(self, user_id, updates, validate=False):
            captured["user_id"] = user_id
            captured["updates"] = updates
            captured["validate"] = validate
            return {"success": True}

    monkeypatch.setattr(personal, "_require_runtime", lambda: (SimpleNamespace(), _Cfg()))
    monkeypatch.setattr(personal, "build_default_skill_registry", lambda: _Registry())

    out = await personal.apply_personal_template(
        personal.TemplateApplyRequest(template_id="skill:writing", enable=True, activate=True),
        user_id="u1",
    )
    assert out["status"] == "success"
    assert out["kind"] == "skill"
    assert captured["user_id"] == "u1"
    assert captured["updates"]["skills"]["overrides"]["writing"]["enabled"] is True
    assert captured["updates"]["skills"]["active"] == "writing"


@pytest.mark.asyncio
async def test_personal_workflow_recovery_filters_recoverable(monkeypatch):
    class _WorkflowEngine:
        def list_runs(self, user_id, limit):
            _ = (user_id, limit)
            return [
                {"workflow_run_id": "r1", "status": "paused"},
                {"workflow_run_id": "r2", "status": "failed", "current_step_id": "step_x"},
                {"workflow_run_id": "r3", "status": "waiting_human"},
                {"workflow_run_id": "r4", "status": "succeeded"},
            ]

    monkeypatch.setattr(
        personal,
        "_require_runtime",
        lambda: (SimpleNamespace(workflow_engine=_WorkflowEngine()), SimpleNamespace()),
    )

    out = await personal.list_personal_workflow_recovery(limit=20, user_id="u1")
    assert out["status"] == "success"
    assert out["total"] == 3
    by_id = {x["workflow_run_id"]: x for x in out["runs"]}
    assert by_id["r1"]["recommended_action"] == "resume"
    assert by_id["r2"]["recommended_action"] == "retry"
    assert by_id["r2"]["retry_step_id"] == "step_x"
    assert by_id["r3"]["recommended_action"] == "resume"


@pytest.mark.asyncio
async def test_personal_export_and_import_bundle(monkeypatch):
    class _Cfg:
        def get_merged_config(self, user_id):
            _ = user_id
            return {"api": {"model": "x"}}

        async def update_user_config(self, user_id, updates, validate=False):
            _ = (user_id, updates, validate)
            return {"success": True, "message": "ok"}

    class _MM:
        def export_user_sessions(self, user_id, include_messages=True):
            _ = (user_id, include_messages)
            return [{"session_id": "s1", "messages": [{"role": "user", "content": "hi"}]}]

        def import_user_sessions(self, user_id, sessions, merge=True):
            _ = (user_id, sessions, merge)
            return {"imported_sessions": 1, "skipped_sessions": 0, "remapped_sessions": 0, "session_ids": ["s1"]}

    class _Adapter:
        def export_mef(self, user_id):
            _ = user_id
            return {"nodes": []}

        def import_mef(self, mef, merge=True):
            _ = (mef, merge)
            return {"ok": True}

    gateway = SimpleNamespace(
        message_manager=_MM(),
        memory_service=SimpleNamespace(memory_adapter=_Adapter()),
    )
    monkeypatch.setattr(personal, "_require_runtime", lambda: (gateway, _Cfg()))
    monkeypatch.setattr(personal.user_manager, "get_user_config", lambda user_id: {"user": user_id})
    monkeypatch.setattr(
        personal.user_file_store,
        "export_user_bundle",
        lambda **kwargs: {"items": [{"file_id": "f1"}], "stats": {"total_files": 1, "total_bytes": 10}, "include_content": bool(kwargs.get("include_content"))},
    )
    monkeypatch.setattr(
        personal.user_file_store,
        "import_user_bundle",
        lambda **kwargs: {"imported_files": 1, "skipped_files": 0},
    )

    exported = await personal.export_personal_bundle(
        personal.PersonalExportRequest(include_messages=True, include_memory=True, include_files=True),
        user_id="u1",
    )
    assert exported["status"] == "success"
    bundle = exported["bundle"]
    assert bundle["bundle_version"] == "personal.v1"
    assert bundle["payload"]["sessions"][0]["session_id"] == "s1"
    assert bundle["payload"]["files"]["stats"]["total_files"] == 1
    assert bundle["payload"]["memory"]["included"] is True

    imported = await personal.import_personal_bundle(
        personal.PersonalImportRequest(
            bundle=bundle,
            merge=True,
            restore_config=True,
            restore_sessions=True,
            restore_memory=True,
            restore_files=True,
        ),
        user_id="u1",
    )
    assert imported["status"] == "success"
    assert imported["applied"]["sessions"]["imported_sessions"] == 1
    assert imported["applied"]["files"]["imported_files"] == 1
    assert imported["applied"]["memory"]["ok"] is True
