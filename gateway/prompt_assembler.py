from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .prompt_blocks import PromptBlock, PromptBlockType
from .protocol import MemoryRecallBundle, ModeDecision, PlanResult, ToolExecutionBundle


class PromptAssembler:
    """Build system prompts from structured prompt blocks."""

    @staticmethod
    def _normalize_block_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        aliases = {
            "identity": "identity",
            "identity_block": "identity",
            "skill": "skill",
            "skill_block": "skill",
            "policy": "policy",
            "policy_block": "policy",
            "memory": "memory",
            "memory_block": "memory",
            "tools": "tools",
            "tools_block": "tools",
            "workspace": "workspace",
            "workspace_block": "workspace",
            "reasoning": "reasoning",
            "reasoning_block": "reasoning",
            "response_format": "response_format",
            "response_format_block": "response_format",
        }
        return aliases.get(text, text)

    def _apply_block_policy(self, blocks: List[PromptBlock], run_context: Optional[Any]) -> List[PromptBlock]:
        if run_context is None:
            return blocks

        policy = getattr(run_context, "prompt_block_policy", None)
        if not isinstance(policy, dict) or not policy:
            return blocks

        disabled_raw = policy.get("disable") or policy.get("disabled") or []
        enabled_raw = policy.get("enable") or policy.get("enabled") or []

        disabled: Set[str] = {self._normalize_block_name(x) for x in disabled_raw}
        disabled.discard("")
        enabled: Set[str] = {self._normalize_block_name(x) for x in enabled_raw}
        enabled.discard("")

        out: List[PromptBlock] = []
        for block in blocks:
            key = self._normalize_block_name(block.block_id)
            if key in disabled:
                continue
            if enabled and key not in enabled:
                continue
            out.append(block)
        return out

    def collect_blocks(
        self,
        *,
        run_context: Optional[Any],
        mode: ModeDecision,
        plan: PlanResult,
        memory_bundle: MemoryRecallBundle,
        tools: ToolExecutionBundle,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> List[PromptBlock]:
        blocks: List[PromptBlock] = []

        identity_content = (plan.system_prompt or plan.base_system_prompt or "").strip()
        if identity_content:
            blocks.append(
                PromptBlock(
                    block_id="identity",
                    block_type=PromptBlockType.IDENTITY,
                    source="conversation.plan",
                    content=identity_content,
                    priority=100,
                    can_compact=False,
                )
            )

        if run_context is not None:
            active_skill = getattr(run_context, "active_skill", None)
            if isinstance(active_skill, dict):
                skill_instruction = str(active_skill.get("system_instruction") or "").strip()
                if skill_instruction:
                    blocks.append(
                        PromptBlock(
                            block_id="skill",
                            block_type=PromptBlockType.SKILL,
                            source="skill_registry",
                            content=skill_instruction,
                            priority=95,
                            can_compact=False,
                            metadata={
                                "skill_id": active_skill.get("skill_id"),
                                "version": active_skill.get("version"),
                            },
                        )
                    )

        if memory_bundle.recalled and memory_bundle.context and not plan.system_prompt:
            blocks.append(
                PromptBlock(
                    block_id="memory",
                    block_type=PromptBlockType.MEMORY,
                    source=memory_bundle.source,
                    content=memory_bundle.context.strip(),
                    priority=80,
                    can_compact=True,
                    metadata={"reason": memory_bundle.reason},
                )
            )

        if mode.mode != "fast" and plan.used_reasoning:
            reasoning_note = str((plan.reasoning or {}).get("final_decision") or "").strip()
            if reasoning_note:
                blocks.append(
                    PromptBlock(
                        block_id="reasoning",
                        block_type=PromptBlockType.REASONING,
                        source="reasoning_service",
                        content=reasoning_note,
                        priority=70,
                        can_compact=True,
                    )
                )

        if tools.enabled:
            blocks.append(
                PromptBlock(
                    block_id="tools",
                    block_type=PromptBlockType.TOOLS,
                    source="tool_runtime",
                    content="Tools are available. Use them only when necessary and policy-compliant.",
                    priority=40,
                    can_compact=True,
                    metadata={"strategy": tools.strategy},
                )
            )

        if run_context is not None:
            workspace = getattr(run_context, "workspace_handle", None) or {}
            if isinstance(workspace, dict) and workspace:
                blocks.append(
                    PromptBlock(
                        block_id="workspace",
                        block_type=PromptBlockType.WORKSPACE,
                        source="run_context.workspace_handle",
                        content=f"Workspace context: {workspace}",
                        priority=30,
                        can_compact=True,
                    )
                )

            policy = getattr(run_context, "tool_policy", None) or {}
            if isinstance(policy, dict) and policy:
                blocks.append(
                    PromptBlock(
                        block_id="policy",
                        block_type=PromptBlockType.POLICY,
                        source="run_context.tool_policy",
                        content=f"Tool policy constraints: {policy}",
                        priority=90,
                        can_compact=False,
                    )
                )

        cfg = user_config or {}
        response_style = str(cfg.get("response_style") or "").strip()
        if response_style:
            blocks.append(
                PromptBlock(
                    block_id="response_format",
                    block_type=PromptBlockType.RESPONSE_FORMAT,
                    source="user_config.response_style",
                    content=f"Response style requirement: {response_style}",
                    priority=35,
                    can_compact=True,
                )
            )

        return self._apply_block_policy(blocks, run_context)

    def sort_blocks(self, blocks: List[PromptBlock]) -> List[PromptBlock]:
        return sorted(blocks, key=lambda b: b.priority, reverse=True)

    def estimate_tokens(self, blocks: List[PromptBlock]) -> Dict[str, int]:
        total = 0
        by_block: Dict[str, int] = {}
        for block in blocks:
            est = block.estimate_tokens()
            by_block[block.block_id] = est
            total += est
        return {"total": total, "by_block": by_block}

    def compact_blocks(self, blocks: List[PromptBlock], budget: Optional[int]) -> Dict[str, Any]:
        if not budget or budget <= 0:
            return {
                "blocks": blocks,
                "dropped_block_ids": [],
                "compacted": False,
            }

        sorted_blocks = self.sort_blocks(blocks)
        stats = self.estimate_tokens(sorted_blocks)
        total = stats["total"]
        if total <= budget:
            return {
                "blocks": sorted_blocks,
                "dropped_block_ids": [],
                "compacted": False,
            }

        dropped: List[str] = []
        kept = list(sorted_blocks)
        for block in reversed(sorted_blocks):
            if total <= budget:
                break
            if not block.can_compact:
                continue
            if block in kept:
                kept.remove(block)
                dropped.append(block.block_id)
                total -= block.token_estimate

        return {
            "blocks": kept,
            "dropped_block_ids": dropped,
            "compacted": len(dropped) > 0,
        }

    def render_prompt(self, blocks: List[PromptBlock]) -> str:
        rendered: List[str] = []
        for block in blocks:
            if not block.enabled:
                continue
            content = (block.content or "").strip()
            if not content:
                continue
            rendered.append(content)
        return "\n\n".join(rendered).strip()

    def assemble(
        self,
        *,
        run_context: Optional[Any],
        mode: ModeDecision,
        plan: PlanResult,
        memory_bundle: MemoryRecallBundle,
        tools: ToolExecutionBundle,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        blocks = self.collect_blocks(
            run_context=run_context,
            mode=mode,
            plan=plan,
            memory_bundle=memory_bundle,
            tools=tools,
            user_config=user_config,
        )
        blocks = self.sort_blocks(blocks)
        estimated = self.estimate_tokens(blocks)

        budget = None
        if run_context is not None:
            budget = getattr(run_context, "token_budget", None)

        compacted = self.compact_blocks(blocks, budget)
        kept_blocks = compacted["blocks"]
        prompt = self.render_prompt(kept_blocks)

        debug = {
            "budget": budget,
            "estimated_total_tokens": estimated["total"],
            "used_block_ids": [b.block_id for b in kept_blocks],
            "blocks": [
                {
                    "block_id": b.block_id,
                    "block_type": b.block_type.value,
                    "source": b.source,
                    "priority": b.priority,
                    "token_estimate": b.token_estimate,
                    "can_compact": b.can_compact,
                }
                for b in blocks
            ],
            "dropped_block_ids": compacted["dropped_block_ids"],
            "compacted": compacted["compacted"],
        }

        if run_context is not None:
            try:
                run_context.prompt_blocks = {
                    "used_block_ids": debug["used_block_ids"],
                    "dropped_block_ids": debug["dropped_block_ids"],
                    "compacted": debug["compacted"],
                    "estimated_total_tokens": debug["estimated_total_tokens"],
                }
            except Exception:
                pass

        return {
            "system_prompt": prompt,
            "blocks": kept_blocks,
            "debug": debug,
        }
