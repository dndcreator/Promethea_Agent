from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillExample(BaseModel):
    title: str
    user_input: str
    assistant_output: str
    notes: Optional[str] = None


class SkillEvaluationCase(BaseModel):
    case_id: str
    title: str
    input: str
    expected_behavior: str
    required_tools: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class SkillSpec(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    category: str = "general"
    system_instruction: str = ""
    tool_allowlist: List[str] = Field(default_factory=list)
    prompt_block_policy: Dict[str, Any] = Field(default_factory=dict)
    default_mode: str = "fast"
    examples: List[SkillExample] = Field(default_factory=list)
    evaluation_cases: List[SkillEvaluationCase] = Field(default_factory=list)
    version: str = "0.1.0"
    enabled: bool = True

    # Runtime/debug metadata.
    source: str = "official"
    pack_path: Optional[str] = None
