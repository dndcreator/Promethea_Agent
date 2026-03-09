from gateway.tool_policy import ToolPolicyEngine


def test_policy_profile_coding_allows_runtime_and_fs_and_moirai():
    engine = ToolPolicyEngine()
    cfg = {"tools": {"profile": "coding"}}

    allow_run = engine.check(
        service_name="computer_control",
        tool_name="execute_command",
        user_config=cfg,
        provider_id="default",
    )
    assert allow_run.allowed is True

    allow_flow = engine.check(
        service_name="moirai",
        tool_name="run_until_pause",
        user_config=cfg,
        provider_id="default",
    )
    assert allow_flow.allowed is True


def test_policy_deny_overrides_allow():
    engine = ToolPolicyEngine()
    cfg = {
        "tools": {
            "profile": "full",
            "deny": ["computer_control.execute_command"],
        }
    }
    decision = engine.check(
        service_name="computer_control",
        tool_name="execute_command",
        user_config=cfg,
        provider_id="default",
    )
    assert decision.allowed is False
    assert "deny" in decision.reason


def test_policy_by_provider_override():
    engine = ToolPolicyEngine()
    cfg = {
        "tools": {
            "profile": "full",
            "byProvider": {
                "openrouter": {
                    "profile": "minimal",
                    "deny": ["group:runtime"],
                }
            },
        }
    }

    blocked = engine.check(
        service_name="computer_control",
        tool_name="execute_command",
        user_config=cfg,
        provider_id="openrouter",
    )
    assert blocked.allowed is False

    allowed = engine.check(
        service_name="websearch",
        tool_name="search",
        user_config=cfg,
        provider_id="openrouter",
    )
    assert allowed.allowed is True
