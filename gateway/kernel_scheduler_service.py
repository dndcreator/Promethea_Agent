from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from agentkit.tools.cron_tools.cron_tools import CronToolsService


class KernelSchedulerService:
    """Kernel-level local scheduler loop for persistent cron jobs."""

    def __init__(
        self,
        *,
        workspace_root: str | None = None,
        tick_seconds: float = 5.0,
        max_jobs_per_tick: int = 10,
        enabled: bool = True,
        cron_service: CronToolsService | None = None,
    ) -> None:
        root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.workspace_root = root
        self.tick_seconds = max(0.2, float(tick_seconds))
        self.max_jobs_per_tick = max(1, int(max_jobs_per_tick))
        self.enabled = bool(enabled)

        self._cron = cron_service or CronToolsService(workspace_root=str(root))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._paused = False
        self._lock = asyncio.Lock()

        self._started_at: Optional[float] = None
        self._last_tick_at: Optional[float] = None
        self._last_result: Dict[str, Any] = {"ok": True, "count": 0, "ran": []}
        self._last_error: str = ""
        self._total_ticks = 0
        self._total_jobs_run = 0

    async def start(self, *, paused: bool = False) -> bool:
        if not self.enabled:
            self._paused = True
            return False
        if self._running:
            return True

        self._running = True
        self._paused = bool(paused)
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run_loop(), name="kernel_scheduler_loop")
        logger.info(
            "Kernel scheduler started (tick={}s, max_jobs_per_tick={})",
            self.tick_seconds,
            self.max_jobs_per_tick,
        )
        return True

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Kernel scheduler stop error: {}", e)
        logger.info("Kernel scheduler stopped")

    async def pause(self) -> None:
        self._paused = True

    async def resume(self) -> None:
        if not self.enabled:
            return
        if not self._running:
            await self.start(paused=False)
            return
        self._paused = False

    async def run_once(self, *, max_jobs: Optional[int] = None) -> Dict[str, Any]:
        max_n = self.max_jobs_per_tick if max_jobs is None else max(1, int(max_jobs))
        async with self._lock:
            ts = time.time()
            self._last_tick_at = ts
            self._total_ticks += 1
            try:
                out = await self._cron.run_due_jobs(now_ts=ts, max_jobs=max_n)
                self._last_result = dict(out or {})
                self._last_error = ""
                ran_count = int(self._last_result.get("count") or 0)
                self._total_jobs_run += max(0, ran_count)
                return self._last_result
            except Exception as e:
                self._last_error = str(e)
                self._last_result = {"ok": False, "count": 0, "ran": [], "error": str(e)}
                logger.warning("Kernel scheduler tick failed: {}", e)
                return dict(self._last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "paused": self._paused,
            "tick_seconds": self.tick_seconds,
            "max_jobs_per_tick": self.max_jobs_per_tick,
            "workspace_root": str(self.workspace_root),
            "started_at": self._started_at,
            "last_tick_at": self._last_tick_at,
            "last_result": dict(self._last_result),
            "last_error": self._last_error,
            "total_ticks": self._total_ticks,
            "total_jobs_run": self._total_jobs_run,
            "loop_alive": bool(self._task and not self._task.done()),
        }

    async def _run_loop(self) -> None:
        try:
            while self._running:
                if not self._paused:
                    await self.run_once()
                await asyncio.sleep(self.tick_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._last_error = str(e)
            logger.exception("Kernel scheduler loop crashed: {}", e)
