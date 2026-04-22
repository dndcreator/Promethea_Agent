from __future__ import annotations

import pytest
from fastapi import HTTPException

from gateway.http.routes import self_evolve


class _CfgSvc:
    def __init__(self, merged):
        self._merged = merged

    def get_merged_config(self, _user_id):
        return dict(self._merged)


class _Svc:
    def __init__(self, enabled: bool):
        self._enabled = enabled

    def resolve_profile(self, _merged):
        return {
            "enabled": self._enabled,
            "max_tasks_list": 10,
            "max_context_chars_per_file": 4000,
            "max_validate_timeout_seconds": 180,
        }

    def status_snapshot(self, _merged):
        return {
            "enabled": self._enabled,
            "profile": self.resolve_profile(_merged),
            "store_path": "memory/self_evolve_tasks.json",
            "task_stats": {"total": 0, "by_status": {}},
            "notice": None if self._enabled else "disabled",
        }

    async def create_task(self, **kwargs):
        _ = kwargs
        return {"ok": True, "task": {"task_id": "se_demo", "status": "planned"}}

    async def list_tasks(self, *, limit: int, status: str = ""):
        return {"ok": True, "total": 1, "limit_used": limit, "status_filter": status, "tasks": [{"task_id": "se_1"}]}

    async def get_task(self, *, task_id: str):
        if task_id == "missing":
            raise FileNotFoundError("task not found: missing")
        return {"ok": True, "task": {"task_id": task_id}}


@pytest.mark.asyncio
async def test_self_evolve_status_exposes_notice_when_disabled(monkeypatch):
    monkeypatch.setattr(
        self_evolve,
        "_get_self_evolve_service",
        lambda: (_Svc(enabled=False), _CfgSvc({"self_evolve": {"enabled": False}})),
    )
    out = await self_evolve.self_evolve_status(current_user_id="u1")
    assert out["status"] == "success"
    assert out["self_evolve"]["enabled"] is False
    assert "disabled" in str(out["self_evolve"]["notice"]).lower()


@pytest.mark.asyncio
async def test_self_evolve_create_task_requires_enabled_feature(monkeypatch):
    monkeypatch.setattr(
        self_evolve,
        "_get_self_evolve_service",
        lambda: (_Svc(enabled=False), _CfgSvc({"self_evolve": {"enabled": False}})),
    )
    with pytest.raises(HTTPException) as ei:
        await self_evolve.self_evolve_create_task(
            self_evolve.SelfEvolveCreateTaskRequest(goal="improve", target_files=["a.py"]),
            current_user_id="u1",
        )
    assert ei.value.status_code == 400
    assert "disabled" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_self_evolve_list_tasks_caps_limit_by_profile(monkeypatch):
    monkeypatch.setattr(
        self_evolve,
        "_get_self_evolve_service",
        lambda: (_Svc(enabled=True), _CfgSvc({"self_evolve": {"enabled": True}})),
    )
    out = await self_evolve.self_evolve_list_tasks(limit=200, task_status="planned", current_user_id="u1")
    assert out["status"] == "success"
    assert out["limit_used"] == 10
    assert out["status_filter"] == "planned"


@pytest.mark.asyncio
async def test_self_evolve_get_task_maps_not_found_to_404(monkeypatch):
    monkeypatch.setattr(
        self_evolve,
        "_get_self_evolve_service",
        lambda: (_Svc(enabled=True), _CfgSvc({"self_evolve": {"enabled": True}})),
    )
    with pytest.raises(HTTPException) as ei:
        await self_evolve.self_evolve_get_task(task_id="missing", current_user_id="u1")
    assert ei.value.status_code == 404
