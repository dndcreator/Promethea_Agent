"""Durable, user-scoped scheduling of arbitrary registered capabilities."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agentkit.mcp.invocation_context import get_invocation_context

from .temporal import next_run_at, normalize_trigger, resolve_timezone_name


_STORE_LOCKS: Dict[str, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


def _store_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(key, threading.RLock())


class TemporalSchedulerService:
    """Persist trigger + target + trusted execution context, independent of UI or language."""

    def __init__(
        self,
        workspace_root: str | None = None,
        *,
        default_misfire_grace_seconds: int = 60,
        lease_seconds: int = 300,
    ):
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_path = self.workspace_root / "memory" / "cron_jobs.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_misfire_grace_seconds = max(0, int(default_misfire_grace_seconds))
        self.lease_seconds = max(30, int(lease_seconds))
        self._tool_executor: Optional[Callable[..., Awaitable[Any]]] = None
        self._confirmation_resolver: Optional[Callable[[str, Dict[str, Any]], bool]] = None

    def configure_tool_runtime(
        self,
        *,
        executor: Callable[..., Awaitable[Any]],
        confirmation_resolver: Callable[[str, Dict[str, Any]], bool],
    ) -> None:
        self._tool_executor = executor
        self._confirmation_resolver = confirmation_resolver

    def _lock(self) -> threading.RLock:
        return _store_lock(self.store_path)

    @staticmethod
    def _invocation_owner() -> str:
        owner = str(get_invocation_context().get("user_id") or "").strip()
        if not owner:
            raise PermissionError("scheduled operations require an authenticated user context")
        return owner

    def _load_jobs(self) -> List[Dict[str, Any]]:
        with self._lock():
            if not self.store_path.exists():
                return []
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"scheduled job store is unreadable: {exc}") from exc
            if not isinstance(raw, list):
                raise RuntimeError("scheduled job store has an invalid structure")
            return [dict(row) for row in raw if isinstance(row, dict)]

    def _save_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        with self._lock():
            temporary = self.store_path.with_name(f".{self.store_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.store_path)
            finally:
                temporary.unlink(missing_ok=True)

    async def create_job(
        self,
        name: str,
        interval_seconds: Optional[int] = None,
        service_name: str = "",
        tool_name: str = "",
        args: Dict[str, Any] | None = None,
        enabled: bool = True,
        trigger: Dict[str, Any] | None = None,
        timezone_name: str = "",
        misfire_policy: str = "run_once",
        misfire_grace_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not str(name or "").strip():
            raise ValueError("name is required")
        if not service_name or not tool_name:
            raise ValueError("service_name and tool_name are required")
        if misfire_policy not in {"run_once", "skip"}:
            raise ValueError("misfire_policy must be run_once or skip")

        context = get_invocation_context()
        owner_user_id = self._invocation_owner()
        resolved_timezone = resolve_timezone_name(requested=timezone_name or str(context.get("timezone") or ""))
        now = time.time()
        normalized_trigger = normalize_trigger(
            trigger,
            interval_seconds=interval_seconds,
            timezone_name=resolved_timezone,
            now_ts=now,
        )
        next_at = next_run_at(normalized_trigger, after_ts=now, timezone_name=resolved_timezone)
        if next_at is None:
            raise ValueError("schedule has no future occurrence")

        target_args = dict(args or {})
        target_params = {
            **target_args,
            "agentType": "tool",
            "service_name": str(service_name).strip(),
            "tool_name": str(tool_name).strip(),
        }
        full_name = f"{target_params['service_name']}.{target_params['tool_name']}"
        if self._confirmation_resolver and self._confirmation_resolver(full_name, target_params):
            raise PermissionError("confirmation-required tools cannot run unattended")

        job_id = f"job_{uuid.uuid4().hex}"
        row = {
            "job_id": job_id,
            "name": str(name).strip(),
            "trigger": normalized_trigger,
            "timezone": resolved_timezone,
            "misfire_policy": misfire_policy,
            "misfire_grace_seconds": (
                self.default_misfire_grace_seconds
                if misfire_grace_seconds is None
                else max(0, int(misfire_grace_seconds))
            ),
            "target": {
                "kind": "tool",
                "service_name": target_params["service_name"],
                "tool_name": target_params["tool_name"],
                "args": target_args,
            },
            "execution_context": {
                "user_id": owner_user_id,
                "session_id": str(context.get("session_id") or ""),
                "workspace_id": str(context.get("workspace_id") or context.get("session_id") or "default"),
                "task_id": str(context.get("task_id") or ""),
                "run_id": str(context.get("run_id") or ""),
                "timezone": resolved_timezone,
            },
            "enabled": bool(enabled),
            "status": "scheduled" if enabled else "paused",
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
            "next_run_at": next_at,
            "last_error": "",
            "run_count": 0,
        }
        with self._lock():
            jobs = self._load_jobs()
            jobs.append(row)
            self._save_jobs(jobs)
        return {"ok": True, "job": row}

    async def list_jobs(self, enabled_only: bool = False) -> Dict[str, Any]:
        owner = self._invocation_owner()
        rows = [row for row in self._load_jobs() if row.get("execution_context", {}).get("user_id") == owner]
        if enabled_only:
            rows = [row for row in rows if bool(row.get("enabled"))]
        rows.sort(key=lambda row: float(row.get("next_run_at") or 0))
        return {"ok": True, "total": len(rows), "jobs": rows}

    async def remove_job(self, job_id: str) -> Dict[str, Any]:
        return self._mutate_owned_job(job_id, remove=True)

    async def pause_job(self, job_id: str) -> Dict[str, Any]:
        return self._mutate_owned_job(job_id, enabled=False)

    async def resume_job(self, job_id: str) -> Dict[str, Any]:
        return self._mutate_owned_job(job_id, enabled=True)

    def _mutate_owned_job(
        self,
        job_id: str,
        *,
        enabled: Optional[bool] = None,
        remove: bool = False,
    ) -> Dict[str, Any]:
        owner = self._invocation_owner()
        with self._lock():
            jobs = self._load_jobs()
            index = next(
                (
                    idx for idx, row in enumerate(jobs)
                    if str(row.get("job_id")) == str(job_id)
                    and row.get("execution_context", {}).get("user_id") == owner
                ),
                None,
            )
            if index is None:
                raise FileNotFoundError(f"scheduled job not found: {job_id}")
            if remove:
                jobs.pop(index)
                self._save_jobs(jobs)
                return {"ok": True, "removed": 1, "job_id": job_id}
            row = jobs[index]
            row["enabled"] = bool(enabled)
            row["status"] = "scheduled" if enabled else "paused"
            row["updated_at"] = time.time()
            if enabled:
                next_at = next_run_at(
                    row["trigger"],
                    after_ts=time.time(),
                    timezone_name=str(row.get("timezone") or "system"),
                )
                row["next_run_at"] = next_at
                if next_at is None:
                    row["enabled"] = False
                    row["status"] = "completed"
            self._save_jobs(jobs)
            return {"ok": True, "job_id": job_id, "enabled": bool(enabled), "job": row}

    async def run_due_jobs(self, now_ts: float | None = None, max_jobs: int = 10) -> Dict[str, Any]:
        return await self._run_due_jobs(
            now_ts=now_ts,
            max_jobs=max_jobs,
            owner_user_id=self._invocation_owner(),
        )

    async def run_due_jobs_internal(self, now_ts: float | None = None, max_jobs: int = 10) -> Dict[str, Any]:
        return await self._run_due_jobs(now_ts=now_ts, max_jobs=max_jobs, owner_user_id=None)

    async def _run_due_jobs(
        self,
        *,
        now_ts: float | None,
        max_jobs: int,
        owner_user_id: Optional[str],
    ) -> Dict[str, Any]:
        now = float(now_ts) if now_ts is not None else time.time()
        claims = self._claim_due_jobs(now=now, max_jobs=max_jobs, owner_user_id=owner_user_id)
        ran: List[Dict[str, Any]] = []
        for claim in claims:
            job = claim["job"]
            lease_id = claim["lease_id"]
            try:
                if self._tool_executor is None or self._confirmation_resolver is None:
                    raise RuntimeError("scheduled capability runtime is not configured")
                target = dict(job.get("target") or {})
                service_name = str(target.get("service_name") or "")
                tool_name = str(target.get("tool_name") or "")
                full_name = f"{service_name}.{tool_name}"
                payload = {
                    **dict(target.get("args") or {}),
                    "agentType": "tool",
                    "service_name": service_name,
                    "tool_name": tool_name,
                }
                if self._confirmation_resolver(full_name, payload):
                    raise PermissionError("scheduled tool requires interactive approval")
                result = await self._tool_executor(
                    full_name,
                    payload,
                    source="scheduler",
                    invocation_context=dict(job.get("execution_context") or {}),
                )
                self._finish_claim(job, lease_id=lease_id, now=now, error="")
                ran.append({"job_id": job.get("job_id"), "ok": True, "result": result})
            except Exception as exc:
                self._finish_claim(job, lease_id=lease_id, now=now, error=str(exc))
                ran.append({"job_id": job.get("job_id"), "ok": False, "error": str(exc)})
        return {"ok": True, "ran": ran, "count": len(ran)}

    def _claim_due_jobs(
        self,
        *,
        now: float,
        max_jobs: int,
        owner_user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        claims: List[Dict[str, Any]] = []
        with self._lock():
            jobs = self._load_jobs()
            for job in jobs:
                context = job.get("execution_context") if isinstance(job.get("execution_context"), dict) else {}
                owner = str(context.get("user_id") or "")
                if not owner or (owner_user_id is not None and owner != owner_user_id):
                    continue
                if not bool(job.get("enabled")) or float(job.get("next_run_at") or 0) > now:
                    continue
                if job.get("status") == "running" and float(job.get("lease_expires_at") or 0) > now:
                    continue
                lateness = now - float(job.get("next_run_at") or 0)
                grace = max(0, int(job.get("misfire_grace_seconds") or 0))
                if str(job.get("misfire_policy") or "run_once") == "skip" and lateness > grace:
                    self._advance(job, now=now)
                    continue
                lease_id = uuid.uuid4().hex
                job["status"] = "running"
                job["lease_id"] = lease_id
                job["lease_expires_at"] = now + self.lease_seconds
                job["updated_at"] = now
                claims.append({"job": dict(job), "lease_id": lease_id})
                if len(claims) >= max(1, int(max_jobs)):
                    break
            self._save_jobs(jobs)
        return claims

    def _finish_claim(self, claimed: Dict[str, Any], *, lease_id: str, now: float, error: str) -> None:
        with self._lock():
            jobs = self._load_jobs()
            row = next((item for item in jobs if item.get("job_id") == claimed.get("job_id")), None)
            if row is None or row.get("lease_id") != lease_id:
                return
            row["last_run_at"] = now
            row["updated_at"] = now
            row["last_error"] = error
            row["run_count"] = int(row.get("run_count") or 0) + 1
            row.pop("lease_id", None)
            row.pop("lease_expires_at", None)
            self._advance(row, now=now)
            if error and not row.get("enabled"):
                row["status"] = "failed"
            self._save_jobs(jobs)

    @staticmethod
    def _advance(row: Dict[str, Any], *, now: float) -> None:
        next_at = next_run_at(
            dict(row.get("trigger") or {}),
            after_ts=now,
            timezone_name=str(row.get("timezone") or "system"),
        )
        if next_at is None:
            row["enabled"] = False
            row["status"] = "completed"
            row["next_run_at"] = None
        else:
            row["status"] = "scheduled"
            row["next_run_at"] = next_at
