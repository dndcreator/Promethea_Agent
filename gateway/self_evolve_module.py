from __future__ import annotations

from typing import Any, Dict, List, Optional

from agentkit.mcp.invocation_context import bind_invocation_context
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
        self_model_service: Optional[Any] = None,
        workspace_root: Optional[str] = None,
    ) -> None:
        self.config_service = config_service
        self.self_model_service = self_model_service
        self.service = SelfEvolveService(
            workspace_root=workspace_root,
            self_model_service=self_model_service,
        )

    @staticmethod
    def resolve_profile(user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = user_config if isinstance(user_config, dict) else {}
        raw = cfg.get("self_evolve") if isinstance(cfg.get("self_evolve"), dict) else {}
        return {
            "enabled": _to_bool(raw.get("enabled"), default=False),
            "max_tasks_list": _as_int(raw.get("max_tasks_list"), 50, minimum=1, maximum=500),
            "max_context_chars_per_file": _as_int(raw.get("max_context_chars_per_file"), 4000, minimum=200, maximum=20000),
            "core_capability": "append_only_capability_evolution",
        }

    def is_enabled(self, user_config: Optional[Dict[str, Any]]) -> bool:
        profile = self.resolve_profile(user_config)
        return bool(profile.get("enabled"))

    def status_snapshot(self, user_config: Optional[Dict[str, Any]], *, user_id: str) -> Dict[str, Any]:
        profile = self.resolve_profile(user_config)
        with bind_invocation_context({"user_id": user_id}):
            state = self.service._load_tasks()
        all_tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
        tasks = {
            task_id: row for task_id, row in all_tasks.items()
            if isinstance(row, dict) and row.get("owner_user_id") == user_id
        }
        status_counts: Dict[str, int] = {}
        for row in tasks.values():
            if not isinstance(row, dict):
                continue
            st = str(row.get("status") or "unknown")
            status_counts[st] = status_counts.get(st, 0) + 1
        notice = (
            None
            if profile.get("enabled")
            else "Self-evolve module is disabled."
        )
        self_model = (
            self.self_model_service.status_snapshot()
            if self.self_model_service is not None
            else {"exists": False, "path": ""}
        )
        return {
            "enabled": bool(profile.get("enabled")),
            "profile": profile,
            "store_path": str(self.service.store_path),
            "staging_root": str(self.service.staging_root),
            "publish_root": str(self.service.publish_root),
            "self_model": self_model,
            "task_stats": {"total": len(tasks), "by_status": status_counts},
            "notice": notice,
        }

    async def create_task(
        self,
        *,
        goal: str,
        capability_id: str,
        version: str,
        description: str,
        commands: List[Dict[str, Any]],
        acceptance_criteria: Optional[List[str]],
        user_id: str,
    ) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_create_task(
                goal=goal,
                capability_id=capability_id,
                version=version,
                description=description,
                commands=commands,
                acceptance_criteria=acceptance_criteria,
            )

    async def list_tasks(self, *, limit: int, status: str = "", user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_list_tasks(limit=limit, status=status)

    async def get_task(self, *, task_id: str, user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_get_task(task_id=task_id)

    async def collect_context(self, *, task_id: str, max_chars_per_file: int, user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_collect_context(
                task_id=task_id,
                max_chars_per_file=max_chars_per_file,
            )

    async def build_self_model(self, *, max_chars_per_file: int) -> Dict[str, Any]:
        return await self.service.evolve_build_self_model(max_chars_per_file=max_chars_per_file)

    async def get_self_model(self) -> Dict[str, Any]:
        return await self.service.evolve_get_self_model()

    async def write_file(self, *, task_id: str, path: str, content: str, user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_write_file(task_id=task_id, path=path, content=content)

    async def validate(self, *, task_id: str, user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_validate(task_id=task_id)

    async def publish(self, *, task_id: str, user_id: str) -> Dict[str, Any]:
        with bind_invocation_context({"user_id": user_id}):
            return await self.service.evolve_publish(task_id=task_id)
