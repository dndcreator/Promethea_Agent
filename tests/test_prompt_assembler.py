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


def test_sort_blocks_by_priority_desc():
    assembler = PromptAssembler()
    blocks = [
        PromptBlock(block_id="a", block_type=PromptBlockType.IDENTITY, source="t", content="1", priority=10),
        PromptBlock(block_id="b", block_type=PromptBlockType.POLICY, source="t", content="2", priority=99),
    ]
    out = assembler.sort_blocks(blocks)
    assert [b.block_id for b in out] == ["b", "a"]


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
    assert isinstance(run_context.prompt_blocks, dict)
    assert "estimated_total_tokens" in run_context.prompt_blocks
