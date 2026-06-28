from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from agentkit.mcp.action_protocol import build_tool_prompt_protocol


def build_tool_execution_prompt(
    *,
    registered_tools: Optional[Iterable[Dict[str, Any]]] = None,
) -> str:
    return build_tool_prompt_protocol(registered_tools=registered_tools)
