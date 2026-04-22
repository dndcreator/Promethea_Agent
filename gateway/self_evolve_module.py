from __future__ import annotations

from typing import Any, Dict, List, Optional

from agentkit.tools.self_evolve.self_evolve import SelfEvolveService


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    out = max(minimum, min(maximum, out))
    return out


class SelfEvolveModule:
    """Gateway-facing self-evolution module, isolated from generic tool runtime wiring."""

    def __init__(
        self,
        *,
        config_service: Optional[Any] = None,
        workspace_root: Optional[str] = None,
    ) -> None:
        self.config_service = config_service
        self.service = SelfEvolveService(workspace_root=workspace_root)

    @staticmethod
    def resolve_profile(user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = user_config if isinstance(user_config, dict) else {}
        raw = cfg.get("self_evolve") if isinstance(cfg.get("self_evolve"), dict) else {}
        return {
            "enabled": _to_bool(raw.get("enabled"), default=False),
            "max_tasks_list": _as_int(raw.get("max_tasks_list"), 50, minimum=1, maximum=500),
            "max_context_chars_per_file": _as_int(raw.get("max_context_chars_per_file"), 4000, minimum=200, maximum=20000),
            "max_validate_timeout_seconds": _as_int(raw.get("max_validate_timeout_seconds"), 180, minimum=5, maximum=1800),
            "core_capability": "controlled_code_evolution",
        }

    def is_enabled(self, user_config: Optional[Dict[str, Any]]) -> bool:
        profile = self.resolve_profile(user_config)
        return bool(profile.get("enabled"))

    def status_snapshot(self, user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile = self.resolve_profile(user_config)
        state = self.service._load_tasks()
        tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
        status_counts: Dict[str, int] = {}
        for row in tasks.values():
            if not isinstance(row, dict):
                continue
            st = str(row.get("status") or "unknown")
            status_counts[st] = status_counts.get(st, 0) + 1
        notice = (
            None
            if profile.get("enabled")
            else "Self-evolve module is disabled; enable self_evolve.enabled to use controlled code evolution endpoints."
        )
        return {
            "enabled": bool(profile.get("enabled")),
            "profile": profile,
            "store_path": str(self.service.store_path),
            "task_stats": {"total": len(tasks), "by_status": status_counts},
            "notice": notice,
        }

    async def create_task(
        self,
        *,
        goal: str,
        target_files: List[str],
        acceptance_criteria: Optional[List[str]],
    ) -> Dict[str, Any]:
        return await self.service.evolve_create_task(
            goal=goal,
            target_files=target_files,
            acceptance_criteria=acceptance_criteria,
        )

    async def list_tasks(self, *, limit: int, status: str = "") -> Dict[str, Any]:
        return await self.service.evolve_list_tasks(limit=limit, status=status)

    async def get_task(self, *, task_id: str) -> Dict[str, Any]:
        return await self.service.evolve_get_task(task_id=task_id)

    async def collect_context(self, *, task_id: str, max_chars_per_file: int) -> Dict[str, Any]:
        return await self.service.evolve_collect_context(
            task_id=task_id,
            max_chars_per_file=max_chars_per_file,
        )

    async def apply_patch(
        self,
        *,
        task_id: str,
        path: str,
        old: str,
        new: str,
        count: int,
        create_backup: bool,
    ) -> Dict[str, Any]:
        return await self.service.evolve_apply_patch(
            task_id=task_id,
            path=path,
            old=old,
            new=new,
            count=count,
            create_backup=create_backup,
        )

    async def validate(
        self,
        *,
        task_id: str,
        command: str,
        cwd: str,
        timeout: int,
    ) -> Dict[str, Any]:
        return await self.service.evolve_validate(
            task_id=task_id,
            command=command,
            cwd=cwd,
            timeout=timeout,
        )
