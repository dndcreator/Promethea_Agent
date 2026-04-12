"""HTTP runtime state singletons."""

from __future__ import annotations

from typing import Any

from agentkit.mcp.mcp_manager import MCPManager
from .metrics import get_metrics_collector

mcp_manager = MCPManager()
metrics = get_metrics_collector()
kernel_scheduler: Any = None
startup_report = {
    "status": "unknown",
    "started_at": None,
    "components": [],
    "summary": {"total": 0, "ok": 0, "degraded": 0, "failed": 0},
}

