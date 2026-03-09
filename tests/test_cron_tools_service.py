from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentkit.tools.cron_tools.cron_tools import CronToolsService


def _make_workspace() -> Path:
    base = Path(".pytest-cron-tools")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


@pytest.mark.asyncio
async def test_cron_create_list_remove():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))

    created = await svc.create_job(
        name="health-check",
        interval_seconds=60,
        service_name="runtime_tools",
        tool_name="gateway_action",
        args={"action": "status"},
    )
    assert created["ok"] is True
    job_id = created["job"]["job_id"]

    listed = await svc.list_jobs()
    assert listed["total"] >= 1

    removed = await svc.remove_job(job_id)
    assert removed["removed"] == 1


@pytest.mark.asyncio
async def test_cron_run_due_jobs(monkeypatch):
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))

    await svc.create_job(
        name="due-job",
        interval_seconds=1,
        service_name="runtime_tools",
        tool_name="gateway_action",
        args={"action": "status"},
    )

    class DummyManager:
        async def unified_call(self, service_name, tool_name, args):
            return {"service": service_name, "tool": tool_name, "args": args}

    monkeypatch.setattr("agentkit.tools.cron_tools.cron_tools.get_mcp_manager", lambda: DummyManager())
    out = await svc.run_due_jobs(now_ts=9999999999, max_jobs=3)
    assert out["ok"] is True
    assert out["count"] >= 1
