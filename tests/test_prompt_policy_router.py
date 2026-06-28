from gateway.prompt_policy_router import DEFAULT_PROMPT_POLICY, PromptPolicyRouter


class _RouterCore:
    def __init__(self, content):
        self.content = content
        self.messages = []

    async def call_llm(self, messages, user_config=None, user_id=None):
        self.messages.append(messages)
        return {"status": "success", "content": self.content}


async def test_prompt_policy_router_parses_llm_json():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"mode":"deep","need_memory":true,"need_reasoning":true,'
            '"need_tools":true,"confidence":0.9,'
            '"reason":"needs project context"}'
        ),
        user_message="help me debug my project",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["source"] == "llm"
    assert policy["mode"] == "deep"
    assert policy["need_memory"] is True
    assert policy["need_reasoning"] is True
    assert policy["need_tools"] is True
    assert "persona_modules" not in policy


async def test_prompt_policy_router_uses_neutral_default_on_invalid_llm_output():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore("not json"),
        user_message="please make a step by step plan to debug this code",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy == DEFAULT_PROMPT_POLICY


async def test_prompt_policy_router_does_not_override_llm_memory_decision():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"mode":"fast","need_memory":false,"need_reasoning":false,'
            '"need_tools":false,"confidence":0.8,'
            '"reason":"model judged no long-term context needed"}'
        ),
        user_message="short personal recall question",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["source"] == "llm"
    assert policy["need_memory"] is False
    assert "heuristic" not in policy["reason"]


async def test_prompt_policy_router_uses_llm_for_memory_decision():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"mode":"fast","need_memory":true,"need_reasoning":false,'
            '"need_tools":false,"confidence":0.9,'
            '"reason":"user asks for remembered personal state"}'
        ),
        user_message="short personal recall question",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["source"] == "llm"
    assert policy["need_memory"] is True


async def test_prompt_policy_router_light_action_keeps_reasoning_light():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"cognitive_mode":"light_action","mode":"fast","reasoning_budget":"small",'
            '"tool_budget":2,"memory_budget":"brief","need_memory":false,'
            '"need_reasoning":false,"need_tools":true,"confidence":0.88,'
            '"reason":"simple current-data lookup"}'
        ),
        user_message="查一下茅台最新股价",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["source"] == "llm"
    assert policy["cognitive_mode"] == "light_action"
    assert policy["mode"] == "fast"
    assert policy["reasoning_budget"] == "small"
    assert policy["tool_budget"] == 3
    assert policy["need_tools"] is True
    assert policy["need_reasoning"] is False


async def test_prompt_policy_router_light_action_keeps_verification_budget():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"cognitive_mode":"light_action","mode":"fast","reasoning_budget":"small",'
            '"tool_budget":1,"memory_budget":"brief","need_memory":false,'
            '"need_reasoning":false,"need_tools":true,"confidence":0.86,'
            '"reason":"simple action with cheap verification"}'
        ),
        user_message="create a small file and confirm it exists",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["cognitive_mode"] == "light_action"
    assert policy["tool_budget"] == 3
    assert policy["reasoning_budget"] == "small"


async def test_prompt_policy_router_direct_ignores_large_reasoning_budget():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"cognitive_mode":"direct","mode":"deep","reasoning_budget":"large",'
            '"tool_budget":5,"need_tools":false,"need_reasoning":true,'
            '"confidence":0.7,"reason":"model over-requested"}'
        ),
        user_message="你好",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["cognitive_mode"] == "direct"
    assert policy["mode"] == "fast"
    assert policy["reasoning_budget"] == "none"
    assert policy["tool_budget"] == 0
    assert policy["need_reasoning"] is False


async def test_prompt_policy_router_includes_structured_runtime_tools():
    core = _RouterCore(
        '{"cognitive_mode":"light_action","mode":"fast","need_tools":true,'
        '"tool_budget":1,"reason":"local command tool is available"}'
    )
    router = PromptPolicyRouter()

    policy = await router.route(
        conversation_core=core,
        user_message="你能打开我电脑的cmd吗",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
        tool_catalog=[
            {
                "name": "computer_control.execute_command",
                "service_name": "computer_control",
                "tool_name": "execute_command",
                "tool_type": "mcp",
                "description": "run a local process",
                "requires_confirmation": True,
                "callable_now": True,
            }
        ],
    )

    assert policy["need_tools"] is True
    assert policy["cognitive_mode"] == "light_action"
    routed_prompt = core.messages[0][1]["content"]
    assert "Runtime registered tools (structured JSON)" in routed_prompt
    assert "computer_control.execute_command" in routed_prompt
    assert '"requires_confirmation":true' in routed_prompt


async def test_prompt_policy_router_includes_runtime_context_and_recent_messages():
    core = _RouterCore(
        '{"cognitive_mode":"light_action","mode":"fast","need_tools":true,'
        '"tool_budget":1,"reason":"ellipsis resolves to AI news search"}'
    )
    router = PromptPolicyRouter()

    policy = await router.route(
        conversation_core=core,
        user_message="那就 AI 吧",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
        tool_catalog=[
            {
                "name": "websearch.news_search",
                "service_name": "websearch",
                "tool_name": "news_search",
                "tool_type": "mcp",
                "description": "Search for news articles",
                "requires_confirmation": False,
                "callable_now": True,
            }
        ],
        runtime_context="Runtime context:\n- Current local date: 2026-05-22",
        recent_messages=[
            {"role": "user", "content": "帮我找一个最新新闻"},
            {"role": "assistant", "content": "中文搜索不稳定，可以换英文主题。"},
        ],
    )

    assert policy["need_tools"] is True
    routed_prompt = core.messages[0][1]["content"]
    assert "Current local date: 2026-05-22" in routed_prompt
    assert "帮我找一个最新新闻" in routed_prompt
    assert "websearch.news_search" in routed_prompt


async def test_prompt_policy_router_action_intent_forces_observation_path():
    router = PromptPolicyRouter()
    policy = await router.route(
        conversation_core=_RouterCore(
            '{"cognitive_mode":"direct","mode":"fast","need_tools":false,'
            '"tool_budget":0,"action_intent":"external_write",'
            '"reason":"desktop file creation requires a runtime side effect"}'
        ),
        user_message="create a file on my desktop",
        user_config={},
        user_id="u1",
        base_system_prompt="You are Promethea.",
    )

    assert policy["action_intent"] == "external_write"
    assert policy["cognitive_mode"] == "light_action"
    assert policy["need_tools"] is True
    assert policy["tool_budget"] == 3


async def test_prompt_policy_router_need_tools_is_never_left_in_direct_mode():
    router = PromptPolicyRouter()
    policy = router.normalize_policy(
        {
            "cognitive_mode": "direct",
            "mode": "fast",
            "need_tools": True,
            "tool_budget": 0,
        },
        source="test",
    )

    assert policy["cognitive_mode"] == "light_action"
    assert policy["need_tools"] is True
    assert policy["tool_budget"] == 3
