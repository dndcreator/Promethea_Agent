from __future__ import annotations

from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class PromptBlockType(str, Enum):
    IDENTITY = "identity_block"
    SKILL = "skill_block"
    POLICY = "policy_block"
    MEMORY = "memory_block"
    TOOLS = "tools_block"
    WORKSPACE = "workspace_block"
    REASONING = "reasoning_block"
    RESPONSE_FORMAT = "response_format_block"


class PromptBlock(BaseModel):
    block_id: str
    block_type: PromptBlockType
    source: str
    content: str
    enabled: bool = True
    priority: int = 50
    token_estimate: int = 0
    can_compact: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def estimate_tokens(self) -> int:
        text = self.content or ""
        estimated = max(1, len(text) // 4) if text.strip() else 0
        self.token_estimate = estimated
        return estimated
