from __future__ import annotations

import asyncio

import pytest

from gateway.kernel_scheduler_service import KernelSchedulerService


class _DummyCronService:
    def __init__(self):
        self.calls = 0

    async def run_due_jobs(self, now_ts=None, max_jobs=10):
        self.calls += 1
        return {"ok": True, "count": 1, "ran": [{"job_id": f"job_{self.calls}"}]}


@pytest.mark.asyncio
async def test_kernel_scheduler_loop_runs_and_stops():
    cron = _DummyCronService()
    scheduler = KernelSchedulerService(
        tick_seconds=0.05,
        max_jobs_per_tick=2,
        enabled=True,
        cron_service=cron,
    )
    started = await scheduler.start()
    assert started is True
    await asyncio.sleep(0.12)
    await scheduler.stop()

    status = scheduler.get_status()
    assert status["running"] is False
    assert status["total_ticks"] >= 1
    assert status["total_jobs_run"] >= 1


@pytest.mark.asyncio
async def test_kernel_scheduler_pause_resume_and_manual_tick():
    cron = _DummyCronService()
    scheduler = KernelSchedulerService(
        tick_seconds=0.2,
        max_jobs_per_tick=3,
        enabled=True,
        cron_service=cron,
    )
    await scheduler.start(paused=True)
    await asyncio.sleep(0.08)
    before = scheduler.get_status()["total_ticks"]
    assert before == 0

    await scheduler.run_once(max_jobs=5)
    mid = scheduler.get_status()["total_ticks"]
    assert mid == 1

    await scheduler.resume()
    await asyncio.sleep(0.25)
    after = scheduler.get_status()["total_ticks"]
    assert after >= 2

    await scheduler.pause()
    paused_state = scheduler.get_status()
    assert paused_state["paused"] is True
    await scheduler.stop()
