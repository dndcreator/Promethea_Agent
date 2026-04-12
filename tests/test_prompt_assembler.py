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
    assert PromptBlockType.PERSONA in block_types


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


def test_persona_module_selected_by_user_message():
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
    assert "persona_core" in ids
    assert "persona_module" in ids
    persona_mod = next((b for b in blocks if b.block_id == "persona_module"), None)
    assert persona_mod is not None
    assert "never change safety" in (persona_mod.content or "").lower()


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
    assert "persona_core" in ids


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
    assert "persona_core" not in ids
    assert "persona_module" not in ids
    assert "soul_core" not in ids
