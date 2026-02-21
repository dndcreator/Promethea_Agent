"""HTTP runtime state singletons."""

from __future__ import annotations

from agentkit.mcp.mcp_manager import MCPManager
from .metrics import get_metrics_collector

mcp_manager = MCPManager()
metrics = get_metrics_collector()

