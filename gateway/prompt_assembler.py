from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from loguru import logger

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
            "persona": "persona",
            "persona_block": "persona",
            "persona_core": "persona",
            "persona_module": "persona",
            "soul": "persona",
            "soul_block": "persona",
            "soul_core": "persona",
            "org_context": "org_context",
            "org_context_block": "org_context",
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

    @staticmethod
    def _apply_org_priority_policy(blocks: List[PromptBlock], run_context: Optional[Any]) -> List[PromptBlock]:
        if run_context is None:
            return blocks
        rs = getattr(run_context, "reasoning_state", None)
        if not isinstance(rs, dict):
            return blocks
        org_ctx = rs.get("org_context") if isinstance(rs.get("org_context"), dict) else {}
        mode = str(org_ctx.get("recall_priority") or "").strip().lower()
        if mode != "override_persona":
            return blocks
        return [b for b in blocks if b.block_id not in {"persona_core", "persona_module", "soul_core"}]

    @staticmethod
    def _resolve_runtime_stability(
        *,
        block_id: str,
        plan: PlanResult,
        source: str,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Classify prompt blocks by runtime stability for cache-friendly ordering.
        - stable: expected to change rarely across turns
        - dynamic: expected to change frequently across turns
        """
        normalized = str(block_id or "").strip().lower()
        if normalized in {"memory", "reasoning", "workspace", "skill", "policy", "persona_module", "org_context"}:
            return "dynamic"
        if normalized == "identity":
            # When reasoning rewrites full system prompt, identity is dynamic.
            if str(plan.system_prompt or "").strip():
                return "dynamic"
            return "stable"
        if normalized == "response_format":
            # Per-user setting; typically stable for a user session.
            return "stable"
        if normalized in {"persona", "persona_core"}:
            return "stable"
        if normalized == "tools":
            # Content is static, but availability is runtime-conditioned.
            # Keep in stable bucket for cache locality when enabled.
            return "stable"
        return "stable"

    @staticmethod
    def _stability_rank(block: PromptBlock) -> int:
        stability = str((block.metadata or {}).get("runtime_stability") or "stable").strip().lower()
        if stability == "dynamic":
            return 1
        return 0

    @staticmethod
    def _default_persona_profile() -> Dict[str, Any]:
        return {
            "enabled": True,
            "core": (
                "Persona layer (style-only): be warm, human-like, and individualized, "
                "while staying factual and task-oriented. Do not override policy, tool, "
                "or reasoning constraints."
            ),
            "soul": {
                "enabled": True,
                "read_only_in_ui": True,
                "auto_evolve": True,
                "content": (
                    "Soul Prompt (blank canvas):\n"
                    "- This is the agent's soul space.\n"
                    "- It starts empty and can evolve over time.\n"
                    "- Keep it style/personality only; never override policy, safety, tools, or reasoning rules."
                ),
            },
            "max_active_modules": 2,
            "modules": {
                "companionship": {
                    "enabled": True,
                    "instruction": (
                        "Companionship tone: emotionally present and calm. "
                        "Acknowledge feelings briefly, then continue with concrete help."
                    ),
                    "triggers": ["lonely", "upset", "anxious", "sad", "support", "comfort"],
                },
                "builder": {
                    "enabled": True,
                    "instruction": (
                        "Builder tone: practical and execution-first. "
                        "Prefer concrete steps and explicit assumptions."
                    ),
                    "triggers": ["implement", "refactor", "debug", "ship", "build", "fix"],
                },
                "creative": {
                    "enabled": True,
                    "instruction": (
                        "Creative tone: allow tasteful imagination and vivid expression, "
                        "without changing factual claims."
                    ),
                    "triggers": ["story", "brand", "narrative", "creative", "copywriting", "idea"],
                },
            },
        }

    @staticmethod
    def _extract_user_text(run_context: Optional[Any]) -> str:
        if run_context is None:
            return ""
        payload = getattr(run_context, "input_payload", None)
        if not isinstance(payload, dict):
            return ""
        text = payload.get("message") or payload.get("query") or payload.get("text") or ""
        return str(text or "").strip().lower()

    @classmethod
    def _resolve_persona_profile(cls, user_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        base = cls._default_persona_profile()
        cfg = user_config if isinstance(user_config, dict) else {}
        raw = cfg.get("persona")
        if not isinstance(raw, dict):
            return base

        merged = dict(base)
        merged["enabled"] = bool(raw.get("enabled", merged.get("enabled", True)))
        core = raw.get("core")
        if isinstance(core, str) and core.strip():
            merged["core"] = core.strip()
        raw_soul = raw.get("soul")
        if isinstance(raw_soul, dict):
            soul = dict(merged.get("soul") or {})
            soul["enabled"] = bool(raw_soul.get("enabled", soul.get("enabled", True)))
            soul["read_only_in_ui"] = bool(
                raw_soul.get("read_only_in_ui", soul.get("read_only_in_ui", True))
            )
            soul["auto_evolve"] = bool(raw_soul.get("auto_evolve", soul.get("auto_evolve", True)))
            soul_content = raw_soul.get("content")
            if isinstance(soul_content, str) and soul_content.strip():
                soul["content"] = soul_content.strip()
            merged["soul"] = soul
        try:
            merged["max_active_modules"] = max(
                0, int(raw.get("max_active_modules", merged.get("max_active_modules", 2)))
            )
        except Exception:
            merged["max_active_modules"] = int(merged.get("max_active_modules", 2))

        modules = dict(base.get("modules") or {})
        raw_modules = raw.get("modules")
        if isinstance(raw_modules, dict):
            for name, mod in raw_modules.items():
                if not isinstance(mod, dict):
                    continue
                key = str(name).strip().lower()
                if not key:
                    continue
                current = dict(modules.get(key) or {})
                current["enabled"] = bool(mod.get("enabled", current.get("enabled", True)))
                if isinstance(mod.get("instruction"), str) and mod.get("instruction", "").strip():
                    current["instruction"] = str(mod.get("instruction")).strip()
                raw_triggers = mod.get("triggers")
                if isinstance(raw_triggers, list):
                    current["triggers"] = [str(x).strip().lower() for x in raw_triggers if str(x).strip()]
                modules[key] = current
        merged["modules"] = modules
        return merged

    @staticmethod
    def _select_persona_modules(
        profile: Dict[str, Any],
        *,
        user_text: str,
        mode: ModeDecision,
    ) -> List[Dict[str, Any]]:
        modules = profile.get("modules")
        if not isinstance(modules, dict):
            return []
        max_active = max(0, int(profile.get("max_active_modules", 2) or 2))
        if max_active <= 0:
            return []

        scored: List[Dict[str, Any]] = []
        for name, row in modules.items():
            if not isinstance(row, dict):
                continue
            if not bool(row.get("enabled", True)):
                continue
            instruction = str(row.get("instruction") or "").strip()
            if not instruction:
                continue
            triggers = row.get("triggers") if isinstance(row.get("triggers"), list) else []
            hits = 0
            for trig in triggers:
                token = str(trig or "").strip().lower()
                if token and token in user_text:
                    hits += 1
            score = hits * 10
            if str(name) == "builder" and mode.mode in {"deep", "workflow"}:
                score += 2
            if score <= 0:
                continue
            scored.append({"name": str(name), "score": score, "instruction": instruction})

        scored.sort(key=lambda x: (-int(x.get("score", 0)), str(x.get("name", ""))))
        return scored[:max_active]

    def _build_persona_blocks(
        self,
        *,
        run_context: Optional[Any],
        mode: ModeDecision,
        plan: PlanResult,
        user_config: Optional[Dict[str, Any]],
    ) -> List[PromptBlock]:
        profile = self._resolve_persona_profile(user_config)
        if not bool(profile.get("enabled", True)):
            return []

        core = str(profile.get("core") or "").strip()
        if not core:
            return []

        blocks: List[PromptBlock] = []
        soul_cfg = profile.get("soul") if isinstance(profile.get("soul"), dict) else {}
        if bool(soul_cfg.get("enabled", True)):
            soul_content = str(soul_cfg.get("content") or "").strip()
            if soul_content:
                blocks.append(
                    PromptBlock(
                        block_id="soul_core",
                        block_type=PromptBlockType.PERSONA,
                        source="user_config.persona.soul",
                        content=soul_content,
                        priority=34,
                        can_compact=True,
                        metadata={
                            "persona_kind": "soul",
                            "runtime_stability": self._resolve_runtime_stability(
                                block_id="soul_core",
                                plan=plan,
                                source="user_config.persona.soul",
                                user_config=user_config,
                            ),
                        },
                    )
                )
        blocks.append(
            PromptBlock(
                block_id="persona_core",
                block_type=PromptBlockType.PERSONA,
                source="user_config.persona.core",
                content=core,
                priority=33,
                can_compact=True,
                metadata={
                    "persona_kind": "core",
                    "runtime_stability": self._resolve_runtime_stability(
                        block_id="persona_core",
                        plan=plan,
                        source="user_config.persona.core",
                        user_config=user_config,
                    ),
                },
            )
        )

        user_text = self._extract_user_text(run_context)
        selected = self._select_persona_modules(profile, user_text=user_text, mode=mode)
        if selected:
            module_lines = [
                (
                    f"[{row['name']}] {row['instruction']} "
                    "Apply only when relevant to this turn. Never change safety, policy, tool, or workflow rules."
                )
                for row in selected
            ]
            blocks.append(
                PromptBlock(
                    block_id="persona_module",
                    block_type=PromptBlockType.PERSONA,
                    source="user_config.persona.modules",
                    content="Persona module selection:\n- " + "\n- ".join(module_lines),
                    priority=32,
                    can_compact=True,
                    metadata={
                        "persona_kind": "module_selection",
                        "selected_modules": [str(row.get("name") or "") for row in selected],
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="persona_module",
                            plan=plan,
                            source="user_config.persona.modules",
                            user_config=user_config,
                        ),
                    },
                )
            )
        return blocks

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
                    metadata={
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="identity",
                            plan=plan,
                            source="conversation.plan",
                            user_config=user_config,
                        )
                    },
                )
            )

        if run_context is not None:
            active_skill = getattr(run_context, "active_skill", None)
            if isinstance(active_skill, dict):
                skill_listing = str(active_skill.get("listing_prompt") or "").strip()
                if not skill_listing:
                    skill_id = str(active_skill.get("skill_id") or "").strip()
                    if skill_id:
                        skill_listing = (
                            "Skills are available via tool `skill.run`.\n"
                            f"Active skill: {skill_id}. Call `skill.run` to load full instructions."
                        )
                if skill_listing:
                    blocks.append(
                        PromptBlock(
                            block_id="skill",
                            block_type=PromptBlockType.SKILL,
                            source="skill_registry",
                            content=skill_listing,
                            priority=95,
                            can_compact=False,
                            metadata={
                                "skill_id": active_skill.get("skill_id"),
                                "version": active_skill.get("version"),
                                "runtime_stability": self._resolve_runtime_stability(
                                    block_id="skill",
                                    plan=plan,
                                    source="skill_registry",
                                    user_config=user_config,
                                ),
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
                    metadata={
                        "reason": memory_bundle.reason,
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="memory",
                            plan=plan,
                            source=memory_bundle.source,
                            user_config=user_config,
                        ),
                    },
                )
            )

        org_context = {}
        if run_context is not None:
            rs = getattr(run_context, "reasoning_state", None)
            if isinstance(rs, dict):
                org_context = rs.get("org_context") if isinstance(rs.get("org_context"), dict) else {}
        org_summary = str(org_context.get("summary_text") or "").strip()
        org_enabled = bool((user_config or {}).get("org_brain", {}).get("enabled")) if isinstance(user_config, dict) else False
        if org_enabled and org_summary:
            blocks.append(
                PromptBlock(
                    block_id="org_context",
                    block_type=PromptBlockType.ORG_CONTEXT,
                    source="org_context_service",
                    content=org_summary,
                    priority=86,
                    can_compact=True,
                    metadata={
                        "org_id": org_context.get("org_id"),
                        "audience": org_context.get("audience"),
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="org_context",
                            plan=plan,
                            source="org_context_service",
                            user_config=user_config,
                        ),
                    },
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
                            metadata={
                                "runtime_stability": self._resolve_runtime_stability(
                                    block_id="reasoning",
                                    plan=plan,
                                    source="reasoning_service",
                                    user_config=user_config,
                                )
                            },
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
                    metadata={
                        "strategy": tools.strategy,
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="tools",
                            plan=plan,
                            source="tool_runtime",
                            user_config=user_config,
                        ),
                    },
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
                            metadata={
                                "runtime_stability": self._resolve_runtime_stability(
                                    block_id="workspace",
                                    plan=plan,
                                    source="run_context.workspace_handle",
                                    user_config=user_config,
                                )
                            },
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
                            metadata={
                                "runtime_stability": self._resolve_runtime_stability(
                                    block_id="policy",
                                    plan=plan,
                                    source="run_context.tool_policy",
                                    user_config=user_config,
                                )
                            },
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
                    metadata={
                        "runtime_stability": self._resolve_runtime_stability(
                            block_id="response_format",
                            plan=plan,
                            source="user_config.response_style",
                            user_config=user_config,
                        )
                    },
                )
            )

        blocks.extend(
            self._build_persona_blocks(
                run_context=run_context,
                mode=mode,
                plan=plan,
                user_config=user_config,
            )
        )

        blocks = self._apply_org_priority_policy(blocks, run_context)
        return self._apply_block_policy(blocks, run_context)

    def sort_blocks(self, blocks: List[PromptBlock]) -> List[PromptBlock]:
        # Cache-friendly deterministic ordering:
        # 1) stable blocks first, 2) then dynamic blocks, 3) within bucket use original priority.
        return sorted(blocks, key=lambda b: (self._stability_rank(b), -int(b.priority or 0)))

    def estimate_tokens(self, blocks: List[PromptBlock]) -> Dict[str, int]:
        total = 0
        by_block: Dict[str, int] = {}
        for block in blocks:
            est = block.estimate_tokens()
            by_block[block.block_id] = est
            total += est
        return {"total": total, "by_block": by_block}

    def _resolve_budget_policy(
        self,
        *,
        run_context: Optional[Any],
        user_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cfg = user_config if isinstance(user_config, dict) else {}
        context_cfg = cfg.get("context_budget") if isinstance(cfg.get("context_budget"), dict) else {}
        strategy = str(context_cfg.get("strategy") or "weighted_truncation").strip() or "weighted_truncation"
        drop_order = str(context_cfg.get("drop_order") or "lowest_priority_compactable_last").strip() or "lowest_priority_compactable_last"
        protect_raw = context_cfg.get("protect") if isinstance(context_cfg.get("protect"), list) else []
        protect = [self._normalize_block_name(x) for x in protect_raw if self._normalize_block_name(x)]

        runtime_policy = getattr(run_context, "debug_flags", {}) if run_context is not None else {}
        if isinstance(runtime_policy, dict):
            override = runtime_policy.get("context_budget_policy")
            if isinstance(override, dict):
                strategy = str(override.get("strategy") or strategy)
                drop_order = str(override.get("drop_order") or drop_order)
                if isinstance(override.get("protect"), list):
                    protect = [self._normalize_block_name(x) for x in override.get("protect") if self._normalize_block_name(x)]

        return {
            "strategy": strategy,
            "drop_order": drop_order,
            "protect": protect,
        }
    def compact_blocks(
        self,
        blocks: List[PromptBlock],
        budget: Optional[int],
        budget_policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
        policy = budget_policy or {}
        protect = set(str(x) for x in (policy.get("protect") or []))
        drop_order = str(policy.get("drop_order") or "lowest_priority_compactable_last").strip()
        if drop_order == "highest_priority_first":
            candidates = list(sorted_blocks)
        else:
            # Keep backward-compatible default: trim from tail of sorted list.
            candidates = list(reversed(sorted_blocks))
        for block in candidates:
            if total <= budget:
                break
            normalized_block = self._normalize_block_name(block.block_id)
            if normalized_block in protect:
                continue
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

        budget_policy = self._resolve_budget_policy(run_context=run_context, user_config=user_config)
        compacted = self.compact_blocks(blocks, budget, budget_policy=budget_policy)
        kept_blocks = compacted["blocks"]
        prompt = self.render_prompt(kept_blocks)

        debug = {
            "budget": budget,
            "estimated_total_tokens": estimated["total"],
            "used_block_ids": [b.block_id for b in kept_blocks],
            "used_static_block_ids": [
                b.block_id
                for b in kept_blocks
                if str((b.metadata or {}).get("runtime_stability") or "stable").strip().lower() != "dynamic"
            ],
            "used_dynamic_block_ids": [
                b.block_id
                for b in kept_blocks
                if str((b.metadata or {}).get("runtime_stability") or "stable").strip().lower() == "dynamic"
            ],
            "blocks": [
                {
                    "block_id": b.block_id,
                    "block_type": b.block_type.value,
                    "source": b.source,
                    "priority": b.priority,
                    "runtime_stability": str((b.metadata or {}).get("runtime_stability") or "stable"),
                    "token_estimate": b.token_estimate,
                    "can_compact": b.can_compact,
                }
                for b in blocks
            ],
            "dropped_block_ids": compacted["dropped_block_ids"],
            "compacted": compacted["compacted"],
            "budget_policy": budget_policy,
        }

        if run_context is not None:
            try:
                run_context.prompt_blocks = {
                    "used_block_ids": debug["used_block_ids"],
                    "used_static_block_ids": debug["used_static_block_ids"],
                    "used_dynamic_block_ids": debug["used_dynamic_block_ids"],
                    "dropped_block_ids": debug["dropped_block_ids"],
                    "compacted": debug["compacted"],
                    "estimated_total_tokens": debug["estimated_total_tokens"],
                }
            except Exception as e:
                logger.debug("PromptAssembler: failed to attach prompt block debug info: {}", e)

        return {
            "system_prompt": prompt,
            "blocks": kept_blocks,
            "debug": debug,
        }

