from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SideEffectLevel(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    PRIVILEGED_HOST_ACTION = "privileged_host_action"


class ToolSource(str, Enum):
    LOCAL = "local"
    MCP = "mcp"
    EXTENSION = "extension"
    AGENT = "agent"


class ToolSpec(BaseModel):
    tool_name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    capability_type: str = "general"
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY
    permission_scope: str = "default"
    timeout_ms: int = 30000
    retry_policy: Dict[str, Any] = Field(default_factory=lambda: {"max_retries": 0})
    idempotency_hint: str = "unknown"
    source: ToolSource = ToolSource.LOCAL
    enabled: bool = True
    service_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def full_name(self) -> str:
        if self.service_name:
            return f"{self.service_name}.{self.tool_name}"
        return self.tool_name
