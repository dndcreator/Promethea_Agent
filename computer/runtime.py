"""Workspace-owned computer controllers behind the existing Gateway boundary."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

from .base import ComputerController, ComputerResult
from .execution_context import ComputerWorkspace


@dataclass
class _WorkspaceControllers:
    controllers: dict[str, ComputerController] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: int = 0
    last_used: float = field(default_factory=time.monotonic)

    def has_background_activity(self) -> bool:
        return any(controller.has_background_activity() for controller in self.controllers.values())

    async def close(self) -> None:
        for controller in self.controllers.values():
            await controller.cleanup()


class ComputerRuntime:
    def __init__(
        self,
        factories: dict[str, Callable[..., ComputerController]],
        *,
        max_workspaces: int = 8,
        capability_aliases: dict[str, str] | None = None,
    ):
        self.factories = factories
        self.capability_aliases = dict(capability_aliases or {})
        self.max_workspaces = max_workspaces
        self._workspaces: dict[ComputerWorkspace, _WorkspaceControllers] = {}
        self._lock = asyncio.Lock()
        self._desktop_lock = asyncio.Lock()
        self._closed = False
        self._tasks: set[asyncio.Task] = set()

    async def execute(self, scope: ComputerWorkspace, capability: str, action: str, params: dict) -> ComputerResult:
        capability = self.capability_aliases.get(capability, capability)
        if capability not in self.factories:
            return ComputerResult(success=False, error=f"Unknown capability: {capability}")
        async with self._lock:
            if self._closed:
                return ComputerResult(success=False, error="Computer runtime is closed")
            entry = self._workspaces.get(scope)
            if entry is None:
                if len(self._workspaces) >= self.max_workspaces:
                    idle = [(key, row) for key, row in self._workspaces.items()
                            if row.active == 0 and not row.has_background_activity()]
                    if not idle:
                        return ComputerResult(success=False, error="Computer workspace capacity reached; active workspaces cannot be evicted")
                    key, row = min(idle, key=lambda item: item[1].last_used)
                    await row.close()
                    del self._workspaces[key]
                entry = self._workspaces[scope] = _WorkspaceControllers()
            entry.active += 1
            task = asyncio.current_task()
            self._tasks.add(task)
        try:
            async with entry.lock:
                controller = entry.controllers.get(capability)
                if controller is None:
                    controller = self.factories[capability](workspace_root=str(scope.root))
                    entry.controllers[capability] = controller
                if not controller.is_initialized and not await controller.initialize():
                    await controller.cleanup()
                    return ComputerResult(success=False, error=f"Controller '{capability}' failed to initialize")
                from agentkit.security.sandbox import get_sandbox_policy

                controller.sandbox = get_sandbox_policy()
                if capability == "screen":
                    async with self._desktop_lock:
                        result = await controller.execute(action, params)
                else:
                    result = await controller.execute(action, params)
                result.metadata["execution"] = {
                    "user_id": scope.user_id,
                    "workspace_id": scope.workspace_id,
                    "workspace_root": str(scope.root),
                    "target": "host",
                    "desktop_isolated": False,
                }
                return result
        finally:
            entry.active -= 1
            entry.last_used = time.monotonic()
            self._tasks.discard(task)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            entries = list(self._workspaces.values())
            tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for entry in entries:
            async with entry.lock:
                await entry.close()
        self._workspaces.clear()
