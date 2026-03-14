from types import SimpleNamespace

from gateway.prompt_assembler import PromptAssembler
from gateway.prompt_blocks import PromptBlockType
from gateway.protocol import MemoryRecallBundle, ModeDecision, PlanResult, RequestMessage, RequestType, ToolExecutionBundle
from gateway.server import GatewayServer
from skills.registry import SkillRegistry


def test_skill_registry_loads_official_pack():
    registry = SkillRegistry()
    loaded = registry.load_official_packs(clear_existing=True)
    assert loaded >= 1

    spec = registry.get_skill("coding_copilot")
    assert spec is not None
    assert spec.default_mode == "deep"
    assert len(spec.examples) >= 1
    assert len(spec.evaluation_cases) >= 1


def test_gateway_server_applies_skill_runtime_context():
    server = GatewayServer()
    request = RequestMessage(
        id="r_skill_1",
        method=RequestType.CHAT,
        params={"message": "hello", "requested_skill": "coding_copilot", "trace_id": "t_skill_1"},
    )
    run_context = server._build_run_context(
        request=request,
        session_id="s_skill_1",
        user_id="u_skill_1",
        channel_id="web",
        input_payload=request.params,
    )

    applied = server._apply_skill_runtime_context(
        run_context=run_context,
        requested_skill="coding_copilot",
        user_config={},
    )

    assert applied is not None
    assert run_context.active_skill.get("skill_id") == "coding_copilot"
    assert run_context.session_state.active_skill_id == "coding_copilot"
    assert run_context.requested_mode == "deep"
    assert len(run_context.tool_policy.get("skill_allowlist") or []) >= 1


def test_prompt_assembler_includes_skill_block_and_policy_filtering():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        active_skill={
            "skill_id": "coding_copilot",
            "version": "1.0.0",
            "system_instruction": "Skill instruction",
        },
        prompt_block_policy={"disable": ["response_format"]},
        tool_policy={},
        workspace_handle={},
        token_budget=None,
        prompt_blocks={},
    )

    blocks = assembler.collect_blocks(
        run_context=run_context,
        mode=ModeDecision(mode="fast", reason="test"),
        plan=PlanResult(used_reasoning=False, base_system_prompt="Base prompt"),
        memory_bundle=MemoryRecallBundle(recalled=False),
        tools=ToolExecutionBundle(enabled=False),
        user_config={"response_style": "brief"},
    )

    block_types = {b.block_type for b in blocks}
    block_ids = {b.block_id for b in blocks}
    assert PromptBlockType.SKILL in block_types
    assert "response_format" not in block_ids
