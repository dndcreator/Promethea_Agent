from __future__ import annotations

from typing import Any, Dict, Optional


class RuntimeHookManager:
    """Best-effort runtime hook manager.

    Default implementation is no-op to preserve existing behavior.
    """

    async def before_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return dict(payload or {})

    async def after_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return dict(payload or {})

    async def on_tool_error(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return dict(payload or {})


_HOOK_MANAGER: Optional[RuntimeHookManager] = None


def get_runtime_hook_manager() -> RuntimeHookManager:
    global _HOOK_MANAGER
    if _HOOK_MANAGER is None:
        _HOOK_MANAGER = RuntimeHookManager()
    return _HOOK_MANAGER

