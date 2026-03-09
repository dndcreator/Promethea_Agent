from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from agentkit.mcp.mcp_manager import get_mcp_manager


class CronToolsService:
    """Persistent cron-like job registry with explicit due-run execution."""

    def __init__(self, workspace_root: str | None = None):
        self.name = "cron_tools"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_path = self.workspace_root / "memory" / "cron_jobs.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    async def create_job(
        self,
        name: str,
        interval_seconds: int,
        service_name: str,
        tool_name: str,
        args: Dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        if not name or not str(name).strip():
            raise ValueError("name is required")
        if int(interval_seconds) <= 0:
            raise ValueError("interval_seconds must be > 0")
        if not service_name or not tool_name:
            raise ValueError("service_name and tool_name are required")

        now = time.time()
        jobs = self._load_jobs()
        job_id = f"job_{uuid.uuid4().hex}"
        row = {
            "job_id": job_id,
            "name": str(name).strip(),
            "interval_seconds": int(interval_seconds),
            "service_name": str(service_name).strip(),
            "tool_name": str(tool_name).strip(),
            "args": dict(args or {}),
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
            "next_run_at": now + int(interval_seconds),
            "last_error": "",
        }
        jobs.append(row)
        self._save_jobs(jobs)
        return {"ok": True, "job": row}

    async def list_jobs(self, enabled_only: bool = False) -> Dict[str, Any]:
        jobs = self._load_jobs()
        rows = [j for j in jobs if j.get("enabled", True)] if enabled_only else jobs
        rows = sorted(rows, key=lambda x: float(x.get("next_run_at") or 0))
        return {"ok": True, "total": len(rows), "jobs": rows}

    async def remove_job(self, job_id: str) -> Dict[str, Any]:
        if not job_id:
            raise ValueError("job_id is required")
        jobs = self._load_jobs()
        before = len(jobs)
        jobs = [j for j in jobs if str(j.get("job_id")) != str(job_id)]
        self._save_jobs(jobs)
        return {"ok": True, "removed": before - len(jobs), "job_id": job_id}

    async def pause_job(self, job_id: str) -> Dict[str, Any]:
        return await self._set_job_enabled(job_id, False)

    async def resume_job(self, job_id: str) -> Dict[str, Any]:
        return await self._set_job_enabled(job_id, True)

    async def run_due_jobs(self, now_ts: float | None = None, max_jobs: int = 10) -> Dict[str, Any]:
        now = float(now_ts) if now_ts else time.time()
        jobs = self._load_jobs()
        manager = get_mcp_manager()

        ran: List[Dict[str, Any]] = []
        for job in jobs:
            if len(ran) >= max(1, int(max_jobs)):
                break
            if not bool(job.get("enabled", True)):
                continue
            next_run_at = float(job.get("next_run_at") or 0)
            if next_run_at > now:
                continue

            try:
                result = await manager.unified_call(
                    service_name=str(job.get("service_name") or ""),
                    tool_name=str(job.get("tool_name") or ""),
                    args=dict(job.get("args") or {}),
                )
                job["last_run_at"] = now
                job["next_run_at"] = now + int(job.get("interval_seconds") or 60)
                job["updated_at"] = now
                job["last_error"] = ""
                ran.append({"job_id": job.get("job_id"), "ok": True, "result": result})
            except Exception as e:
                job["last_run_at"] = now
                job["next_run_at"] = now + int(job.get("interval_seconds") or 60)
                job["updated_at"] = now
                job["last_error"] = str(e)
                ran.append({"job_id": job.get("job_id"), "ok": False, "error": str(e)})

        self._save_jobs(jobs)
        return {"ok": True, "ran": ran, "count": len(ran)}

    async def _set_job_enabled(self, job_id: str, enabled: bool) -> Dict[str, Any]:
        if not job_id:
            raise ValueError("job_id is required")
        jobs = self._load_jobs()
        updated = False
        now = time.time()
        for job in jobs:
            if str(job.get("job_id")) == str(job_id):
                job["enabled"] = bool(enabled)
                job["updated_at"] = now
                if enabled and not job.get("next_run_at"):
                    job["next_run_at"] = now + int(job.get("interval_seconds") or 60)
                updated = True
                break
        self._save_jobs(jobs)
        return {"ok": updated, "job_id": job_id, "enabled": bool(enabled)}

    def _load_jobs(self) -> List[Dict[str, Any]]:
        if not self.store_path.exists():
            return []
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [x for x in raw if isinstance(x, dict)]
            return []
        except Exception:
            return []

    def _save_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        self.store_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
