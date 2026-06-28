from types import SimpleNamespace

from gateway.prompt_assembler import PromptAssembler
from gateway.prompt_blocks import PromptBlock, PromptBlockType
from gateway.protocol import MemoryRecallBundle, ModeDecision, PlanResult, ToolExecutionBundle


def test_prompt_block_estimate_tokens():
    block = PromptBlock(
        block_id="identity",
        block_type=PromptBlockType.IDENTITY,
        source="test",
        content="a" * 40,
    )
    assert block.estimate_tokens() == 10


def test_collect_blocks_contains_expected_types():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(workspace_handle={"project": "agent"}, tool_policy={"allow": ["search"]})

    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(
            used_reasoning=True,
            base_system_prompt="Base prompt",
            reasoning={"final_decision": "Plan in steps"},
        ),
        memory_bundle=MemoryRecallBundle(recalled=True, context="memory context", source="memory_service"),
        tools=ToolExecutionBundle(enabled=True, strategy="llm_native"),
        user_config={"response_style": "concise bullet points"},
    )

    block_types = {b.block_type for b in blocks}
    assert PromptBlockType.IDENTITY in block_types
    assert PromptBlockType.MEMORY in block_types
    assert PromptBlockType.REASONING in block_types
    assert PromptBlockType.TOOLS in block_types
    assert PromptBlockType.WORKSPACE in block_types
    assert PromptBlockType.POLICY in block_types
    assert PromptBlockType.RESPONSE_FORMAT in block_types
    assert PromptBlockType.SOUL in block_types


def test_user_customization_block_is_separate_from_identity():
    assembler = PromptAssembler()
    blocks = assembler.collect_blocks(
        run_context=None,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="You are Promethea."),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={
            "agent_name": "EDI",
            "system_prompt": "Speak in a calm tactical style.",
        },
    )

    identity = next(b for b in blocks if b.block_id == "identity")
    customization = next(b for b in blocks if b.block_id == "customization")
    assert "You are Promethea" in identity.content
    assert "Active display name: EDI" in customization.content
    assert "Speak in a calm tactical style" in customization.content
    assert "cannot override the Promethea core identity" in customization.content
    assert customization.block_type == PromptBlockType.CUSTOMIZATION
    assert customization.priority < identity.priority


def test_user_customization_not_injected_for_empty_default_identity():
    assembler = PromptAssembler()
    blocks = assembler.collect_blocks(
        run_context=None,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="You are Promethea."),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={"agent_name": "Promethea", "system_prompt": ""},
    )

    assert "customization" not in {b.block_id for b in blocks}


def test_tools_block_uses_live_registered_tool_snapshot():
    assembler = PromptAssembler()
    blocks = assembler.collect_blocks(
        run_context=None,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(
            enabled=True,
            metadata={
                "registered_tools": [
                    {
                        "name": "computer_control.write_file",
                        "service_name": "computer_control",
                        "tool_name": "write_file",
                        "tool_type": "mcp",
                        "callable_now": True,
                    }
                ]
            },
        ),
        user_config={},
    )

    tools_block = next(b for b in blocks if b.block_type == PromptBlockType.TOOLS)
    assert "Runtime registered tools (structured JSON)" in tools_block.content
    assert "computer_control.write_file" in tools_block.content
    assert '"callable_now":true' in tools_block.content
    assert "math.calculate" not in tools_block.content


def test_reasoning_block_asks_for_deep_user_facing_synthesis():
    assembler = PromptAssembler()

    blocks = assembler.collect_blocks(
        run_context=None,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(
            used_reasoning=True,
            base_system_prompt="Base prompt",
            reasoning={"reasoning_summary": "Evidence and conclusions from the reasoning tree."},
        ),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={},
    )

    reasoning_block = next(b for b in blocks if b.block_type == PromptBlockType.REASONING)
    assert "Deep reasoning synthesis context" in reasoning_block.content
    assert "substantive synthesis" in reasoning_block.content
    assert "Do not mention hidden reasoning" in reasoning_block.content


def test_sort_blocks_by_priority_desc():
    assembler = PromptAssembler()
    blocks = [
        PromptBlock(
            block_id="a",
            block_type=PromptBlockType.IDENTITY,
            source="t",
            content="1",
            priority=10,
            metadata={"runtime_stability": "stable"},
        ),
        PromptBlock(
            block_id="b",
            block_type=PromptBlockType.POLICY,
            source="t",
            content="2",
            priority=99,
            metadata={"runtime_stability": "stable"},
        ),
    ]
    out = assembler.sort_blocks(blocks)
    assert [b.block_id for b in out] == ["b", "a"]


def test_sort_blocks_prefers_stable_bucket_before_dynamic():
    assembler = PromptAssembler()
    blocks = [
        PromptBlock(
            block_id="dynamic_high",
            block_type=PromptBlockType.POLICY,
            source="t",
            content="x",
            priority=99,
            metadata={"runtime_stability": "dynamic"},
        ),
        PromptBlock(
            block_id="stable_low",
            block_type=PromptBlockType.RESPONSE_FORMAT,
            source="t",
            content="y",
            priority=10,
            metadata={"runtime_stability": "stable"},
        ),
    ]
    out = assembler.sort_blocks(blocks)
    assert [b.block_id for b in out] == ["stable_low", "dynamic_high"]


def test_compact_blocks_drops_low_priority_compactable():
    assembler = PromptAssembler()
    blocks = [
        PromptBlock(
            block_id="must_keep",
            block_type=PromptBlockType.IDENTITY,
            source="t",
            content="x" * 120,
            priority=100,
            can_compact=False,
        ),
        PromptBlock(
            block_id="drop_me",
            block_type=PromptBlockType.MEMORY,
            source="t",
            content="y" * 120,
            priority=20,
            can_compact=True,
        ),
    ]
    assembler.estimate_tokens(blocks)
    result = assembler.compact_blocks(blocks, budget=40)
    kept_ids = [b.block_id for b in result["blocks"]]

    assert "must_keep" in kept_ids
    assert "drop_me" not in kept_ids
    assert "drop_me" in result["dropped_block_ids"]
    assert result["compacted"] is True


def test_assemble_outputs_debug_and_updates_run_context_prompt_blocks():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(token_budget=20, prompt_blocks={})

    out = assembler.assemble(
        run_context=run_context,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="base"),
        memory_bundle=MemoryRecallBundle(recalled=True, context="m" * 400, source="memory_service"),
        tools=ToolExecutionBundle(enabled=False),
        user_config=None,
    )

    assert isinstance(out["system_prompt"], str)
    assert "debug" in out
    assert "used_block_ids" in out["debug"]
    assert "used_static_block_ids" in out["debug"]
    assert "used_dynamic_block_ids" in out["debug"]
    assert isinstance(run_context.prompt_blocks, dict)
    assert "estimated_total_tokens" in run_context.prompt_blocks


def test_compact_blocks_respects_protect_list():
    assembler = PromptAssembler()
    blocks = [
        PromptBlock(
            block_id="identity",
            block_type=PromptBlockType.IDENTITY,
            source="t",
            content="x" * 200,
            priority=100,
            can_compact=False,
        ),
        PromptBlock(
            block_id="memory",
            block_type=PromptBlockType.MEMORY,
            source="t",
            content="m" * 200,
            priority=20,
            can_compact=True,
        ),
        PromptBlock(
            block_id="tools",
            block_type=PromptBlockType.TOOLS,
            source="t",
            content="t" * 200,
            priority=10,
            can_compact=True,
        ),
    ]
    assembler.estimate_tokens(blocks)
    result = assembler.compact_blocks(
        blocks,
        budget=60,
        budget_policy={"protect": ["memory"]},
    )
    kept_ids = [b.block_id for b in result["blocks"]]
    assert "memory" in kept_ids
    assert "tools" not in kept_ids


def test_soul_block_is_injected_without_persona_modules():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        input_payload={"message": "I feel anxious, can you keep me company and help me debug"},
    )
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={},
    )
    ids = [b.block_id for b in blocks]
    assert "soul_core" in ids
    assert "persona_core" not in ids
    assert "persona_module" not in ids
    soul = next((b for b in blocks if b.block_id == "soul_core"), None)
    assert soul is not None
    assert soul.block_type == PromptBlockType.SOUL


def test_prompt_policy_persona_modules_are_ignored_after_soul_unification():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        input_payload={"message": "plain request"},
        prompt_policy={"persona_modules": ["creative"]},
    )
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={},
    )
    persona_mod = next((b for b in blocks if b.block_id == "persona_module"), None)
    assert persona_mod is None
    assert "soul_core" in {b.block_id for b in blocks}


def test_prompt_block_policy_disable_persona_hides_all_persona_blocks():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        input_payload={"message": "I feel anxious"},
        prompt_block_policy={"disable": ["persona"]},
    )
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={},
    )
    ids = {b.block_id for b in blocks}
    assert "soul_core" not in ids
    assert "persona_core" not in ids
    assert "persona_module" not in ids


def test_soul_disabled_removes_soul_block_only():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(input_payload={"message": "hello"})
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={"persona": {"soul": {"enabled": False}}},
    )
    ids = {b.block_id for b in blocks}
    assert "soul_core" not in ids
    assert "persona_core" not in ids


def test_org_context_block_injected_when_enabled_and_recalled():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        reasoning_state={
            "org_context": {
                "summary_text": "Organization context hints:\n- [董事会/formal] 三大战略: 强调长期稳健增长",
                "org_id": "org_demo",
                "audience": "董事会",
            }
        }
    )
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={"org_brain": {"enabled": True}},
    )
    org_block = next((b for b in blocks if b.block_id == "org_context"), None)
    assert org_block is not None
    assert org_block.block_type == PromptBlockType.ORG_CONTEXT
    assert "organization context hints" in (org_block.content or "").lower()


def test_org_context_override_persona_drops_persona_blocks():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        reasoning_state={
            "org_context": {
                "summary_text": "Organization context hints:\n- [董事会/formal] 三大战略: 强调长期稳健增长",
                "org_id": "org_demo",
                "audience": "董事会",
                "recall_priority": "override_persona",
            }
        },
        input_payload={"message": "I feel anxious and need help"},
    )
    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="deep", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={"org_brain": {"enabled": True}},
    )
    ids = {b.block_id for b in blocks}
    assert "org_context" in ids
    assert "soul_core" not in ids
