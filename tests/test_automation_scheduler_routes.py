from __future__ import annotations

import pytest

from gateway.http import state
from gateway.http.routes import automation


class _DummyScheduler:
    def __init__(self):
        self.paused = False
        self.runs = 0

    def get_status(self):
        return {
            "enabled": True,
            "running": True,
            "paused": self.paused,
            "tick_seconds": 5.0,
            "max_jobs_per_tick": 10,
            "total_ticks": self.runs,
            "total_jobs_run": self.runs,
        }

    async def run_once(self, max_jobs=10):
        self.runs += 1
        return {"ok": True, "count": 1, "max_jobs": max_jobs}

    async def pause(self):
        self.paused = True

    async def resume(self):
        self.paused = False


@pytest.mark.asyncio
async def test_scheduler_status_unavailable(monkeypatch):
    monkeypatch.setattr(state, "kernel_scheduler", None, raising=False)
    out = await automation.get_scheduler_status()
    assert out["status"] == "unavailable"
    assert out["scheduler"]["running"] is False


@pytest.mark.asyncio
async def test_scheduler_controls(monkeypatch):
    scheduler = _DummyScheduler()
    monkeypatch.setattr(state, "kernel_scheduler", scheduler, raising=False)

    run_out = await automation.run_scheduler_once(
        request=automation.SchedulerRunOnceRequest(max_jobs=7),
        x_automation_token=None,
    )
    assert run_out["status"] == "success"
    assert run_out["result"]["ok"] is True
    assert run_out["result"]["max_jobs"] == 7

    pause_out = await automation.pause_scheduler(x_automation_token=None)
    assert pause_out["status"] == "success"
    assert pause_out["scheduler"]["paused"] is True

    resume_out = await automation.resume_scheduler(x_automation_token=None)
    assert resume_out["status"] == "success"
    assert resume_out["scheduler"]["paused"] is False
