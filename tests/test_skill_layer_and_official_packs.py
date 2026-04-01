from types import SimpleNamespace

from gateway.prompt_assembler import PromptAssembler
from gateway.prompt_blocks import PromptBlockType
from gateway.protocol import MemoryRecallBundle, ModeDecision, PlanResult, RequestMessage, RequestType, ToolExecutionBundle
from gateway.server import GatewayServer
from skills.registry import SkillRegistry
from skills.schema import SkillSpec


def test_skill_registry_loads_official_pack():
    registry = SkillRegistry()
    loaded = registry.load_official_packs(clear_existing=True)
    assert loaded >= 1

    spec = registry.get_skill("coding_copilot")
    assert spec is not None
    assert spec.default_mode == "deep"
    assert spec.model_invocable is True
    assert spec.execution_context in {"inline", "fork"}
    assert len(spec.allowed_tools) >= 1
    assert len(spec.examples) >= 1
    assert len(spec.evaluation_cases) >= 1


def test_skill_registry_build_listing_prompt_budgeted():
    registry = SkillRegistry()
    registry.load_official_packs(clear_existing=True)
    listing = registry.build_listing_prompt(user_config={}, max_chars=220, per_skill_desc_limit=40)
    assert isinstance(listing.get("listing_prompt"), str)
    assert listing.get("listing_prompt", "").startswith("Skills are available via tool `skill.run`.")
    assert listing.get("count", 0) >= 1


def test_skill_registry_listing_filters_model_invocable_skills():
    registry = SkillRegistry(packs_root="")
    registry.register(
        SkillSpec(skill_id="s_a", name="A", model_invocable=True, description="x", when_to_use="x")
    )
    registry.register(
        SkillSpec(skill_id="s_b", name="B", model_invocable=False, description="y", when_to_use="y")
    )
    listing = registry.build_listing_prompt(user_config={}, max_chars=1000, per_skill_desc_limit=80)
    ids = {row.get("skill_id") for row in (listing.get("skills") or [])}
    assert "s_a" in ids
    assert "s_b" not in ids


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
    assert run_context.active_skill.get("lazy_injection") is True
    assert "skill.run" in (run_context.active_skill.get("listing_prompt") or "")
    assert run_context.session_state.active_skill_id == "coding_copilot"
    assert run_context.requested_mode == "deep"
    assert "skill.run" in (run_context.tool_policy.get("skill_allowlist") or [])
    assert isinstance(run_context.active_skill.get("allowed_tools"), list)


def test_prompt_assembler_includes_skill_listing_block_and_policy_filtering():
    assembler = PromptAssembler()
    run_context = SimpleNamespace(
        active_skill={
            "skill_id": "coding_copilot",
            "version": "1.0.0",
            "system_instruction": "Skill full instruction should not be injected by default",
            "listing_prompt": "Skills are available via tool `skill.run`.\\n- coding_copilot: engineer coding tasks",
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
    skill_block = next((b for b in blocks if b.block_id == "skill"), None)
    assert PromptBlockType.SKILL in block_types
    assert "response_format" not in block_ids
    assert skill_block is not None
    assert "skill.run" in (skill_block.content or "")
    assert "full instruction" not in (skill_block.content or "")
