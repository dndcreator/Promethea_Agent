from __future__ import annotations

import asyncio
import shutil
import os
from pathlib import Path

import pytest

from gateway.temporal_scheduler import TemporalSchedulerService

CronToolsService = TemporalSchedulerService
from agentkit.mcp.invocation_context import bind_invocation_context


@pytest.fixture(autouse=True)
def _scheduler_user_context():
    with bind_invocation_context(
        {"user_id": "u1", "session_id": "s1", "workspace_id": "w1", "timezone": "UTC"}
    ):
        yield


def _make_workspace() -> Path:
    base = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", ".tmp/pytest-runtime")) / "cron-tools"
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
async def test_cron_run_due_jobs():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))

    await svc.create_job(
        name="due-job",
        interval_seconds=1,
        service_name="runtime_tools",
        tool_name="gateway_action",
        args={"action": "status"},
    )

    async def execute(tool_name, params, **kwargs):
        return {
            "tool": tool_name,
            "params": params,
            "source": kwargs.get("source"),
            "context": kwargs.get("invocation_context"),
        }

    svc.configure_tool_runtime(
        executor=execute,
        confirmation_resolver=lambda _name, _params: False,
    )
    out = await svc.run_due_jobs(now_ts=9999999999, max_jobs=3)
    assert out["ok"] is True
    assert out["count"] >= 1
    assert out["ran"][0]["result"]["source"] == "scheduler"
    assert out["ran"][0]["result"]["context"]["user_id"] == "u1"
    assert out["ran"][0]["result"]["context"]["workspace_id"] == "w1"


@pytest.mark.asyncio
async def test_cron_rejects_interactive_approval_in_background():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))
    await svc.create_job(
        name="unsafe-job",
        interval_seconds=1,
        service_name="computer_control",
        tool_name="process_action",
        args={"action": "run", "command": "echo no"},
    )

    async def execute(*_args, **_kwargs):
        raise AssertionError("confirmation-required tool must not execute")

    svc.configure_tool_runtime(
        executor=execute,
        confirmation_resolver=lambda _name, _params: True,
    )
    out = await svc.run_due_jobs(now_ts=9999999999)
    assert out["ran"][0]["ok"] is False
    assert "interactive approval" in out["ran"][0]["error"]


@pytest.mark.asyncio
async def test_cron_rejects_confirmation_required_target_when_created():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))
    svc.configure_tool_runtime(
        executor=lambda *_args, **_kwargs: None,
        confirmation_resolver=lambda _name, _params: True,
    )
    with pytest.raises(PermissionError, match="unattended"):
        await svc.create_job(
            name="unsafe-job",
            interval_seconds=60,
            service_name="computer_control",
            tool_name="process_action",
        )


@pytest.mark.asyncio
async def test_one_shot_job_completes_after_execution():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))
    created = await svc.create_job(
        name="one-shot",
        trigger={"type": "at", "at": "2099-01-01T00:00:00Z"},
        service_name="runtime_tools",
        tool_name="gateway_action",
    )
    svc.configure_tool_runtime(
        executor=lambda *_args, **_kwargs: _async_result({"ok": True}),
        confirmation_resolver=lambda *_: False,
    )
    due = float(created["job"]["next_run_at"])
    assert (await svc.run_due_jobs_internal(now_ts=due))["count"] == 1
    row = (await svc.list_jobs())["jobs"][0]
    assert row["status"] == "completed"
    assert row["enabled"] is False
    assert row["next_run_at"] is None


@pytest.mark.asyncio
async def test_target_arguments_cannot_override_scheduled_route():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))
    created = await svc.create_job(
        name="fixed-route",
        interval_seconds=1,
        service_name="runtime_tools",
        tool_name="gateway_action",
        args={"service_name": "other", "tool_name": "other", "agentType": "local"},
    )
    observed = {}

    async def execute(tool_name, params, **_kwargs):
        observed.update({"tool_name": tool_name, "params": params})
        return {"ok": True}

    svc.configure_tool_runtime(executor=execute, confirmation_resolver=lambda *_: False)
    await svc.run_due_jobs_internal(now_ts=float(created["job"]["next_run_at"]))
    assert observed["tool_name"] == "runtime_tools.gateway_action"
    assert observed["params"]["service_name"] == "runtime_tools"
    assert observed["params"]["tool_name"] == "gateway_action"
    assert observed["params"]["agentType"] == "tool"


@pytest.mark.asyncio
async def test_scheduled_jobs_are_private_to_their_owner():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws))
    created = await svc.create_job(
        name="private-job",
        interval_seconds=60,
        service_name="runtime_tools",
        tool_name="gateway_action",
    )
    with bind_invocation_context({"user_id": "u2", "timezone": "UTC"}):
        assert (await svc.list_jobs())["jobs"] == []
        with pytest.raises(FileNotFoundError):
            await svc.pause_job(created["job"]["job_id"])


@pytest.mark.asyncio
async def test_misfire_skip_uses_grace_instead_of_skipping_normal_tick_delay():
    ws = _make_workspace()
    svc = CronToolsService(workspace_root=str(ws), default_misfire_grace_seconds=10)
    created = await svc.create_job(
        name="grace-job",
        interval_seconds=60,
        service_name="runtime_tools",
        tool_name="gateway_action",
        misfire_policy="skip",
    )
    due = float(created["job"]["next_run_at"])
    calls = []

    async def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    svc.configure_tool_runtime(executor=execute, confirmation_resolver=lambda *_: False)
    assert (await svc.run_due_jobs(now_ts=due + 2))["count"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_due_job_claim_prevents_duplicate_execution_across_instances():
    ws = _make_workspace()
    first = CronToolsService(workspace_root=str(ws))
    second = CronToolsService(workspace_root=str(ws))
    created = await first.create_job(
        name="single-claim",
        interval_seconds=1,
        service_name="runtime_tools",
        tool_name="gateway_action",
    )
    calls = 0

    async def execute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"ok": True}

    for service in (first, second):
        service.configure_tool_runtime(executor=execute, confirmation_resolver=lambda *_: False)
    due = float(created["job"]["next_run_at"])
    results = await asyncio.gather(
        first.run_due_jobs_internal(now_ts=due + 1),
        second.run_due_jobs_internal(now_ts=due + 1),
    )
    assert sum(result["count"] for result in results) == 1
    assert calls == 1


def test_corrupt_schedule_store_fails_loudly():
    ws = _make_workspace()
    service = CronToolsService(workspace_root=str(ws))
    service.store_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        service._load_jobs()


async def _async_result(value):
    return value
