from types import SimpleNamespace

import pytest

from gateway.tools import ToolPolicy, ToolRegistry
from gateway.tools.policy import ToolPolicyDecision
from gateway.tools.spec import SideEffectLevel, ToolSource, ToolSpec


class _DummyLocalTool:
    tool_id = "local.echo"
    name = "echo"
    description = "Echo value"

    async def invoke(self, args, ctx=None):
        return args


def test_toolspec_create():
    spec = ToolSpec(
        tool_name="search",
        service_name="websearch",
        description="search web",
        source=ToolSource.MCP,
    )
    assert spec.full_name == "websearch.search"
    assert spec.side_effect_level == SideEffectLevel.READ_ONLY


def test_registry_register_and_resolve_local():
    registry = ToolRegistry()
    registry.register_local_tool(_DummyLocalTool())

    spec = registry.resolve(tool_name="local.echo", params={})
    assert spec.full_name == "local.echo"
    assert spec.source == ToolSource.LOCAL


def test_policy_allow_deny():
    policy = ToolPolicy()
    spec = ToolSpec(
        tool_name="search",
        service_name="websearch",
        source=ToolSource.MCP,
        side_effect_level=SideEffectLevel.READ_ONLY,
    )
    run_context = SimpleNamespace(tool_policy={"deny": {"websearch.search"}})

    decision = policy.evaluate(spec=spec, run_context=run_context, user_config=None)
    assert isinstance(decision, ToolPolicyDecision)
    assert decision.allowed is False


def test_side_effect_tool_allowed_by_default_for_flexible_runtime():
    policy = ToolPolicy()
    spec = ToolSpec(
        tool_name="write_file",
        service_name="computer_control",
        source=ToolSource.MCP,
        side_effect_level=SideEffectLevel.WORKSPACE_WRITE,
    )
    run_context = SimpleNamespace(tool_policy={})

    decision = policy.evaluate(spec=spec, run_context=run_context, user_config=None)
    assert decision.allowed is True


def test_side_effect_tool_can_be_strictly_gated_when_requested():
    policy = ToolPolicy()
    spec = ToolSpec(
        tool_name="write_file",
        service_name="computer_control",
        source=ToolSource.MCP,
        side_effect_level=SideEffectLevel.WORKSPACE_WRITE,
    )
    run_context = SimpleNamespace(tool_policy={"strict_side_effect_allowlist": True})

    decision = policy.evaluate(spec=spec, run_context=run_context, user_config=None)
    assert decision.allowed is False
    assert "explicit allow" in decision.reason


def test_mcp_registry_mapping():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "websearch",
                    "description": "web tools",
                    "available_tools": [
                        {"name": "search", "description": "search web"},
                        {"name": "news", "description": "news search"},
                    ],
                }
            ]
        }
    )

    spec = registry.resolve(tool_name="websearch", params={"service_name": "websearch", "tool_name": "search"})
    assert spec.full_name == "websearch.search"
    assert spec.source == ToolSource.MCP


def test_registry_normalizes_swapped_mcp_tool_call():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "computer_control",
                    "description": "computer tools",
                    "available_tools": [
                        {"name": "execute_command", "description": "run a shell command"},
                    ],
                }
            ]
        }
    )

    tool_name, params = registry.normalize_call(
        tool_name="computer_control",
        params={
            "agentType": "local",
            "service_name": "execute_command",
            "command": "echo hello",
        },
    )

    assert tool_name == "computer_control.execute_command"
    assert params["agentType"] == "mcp"
    assert params["service_name"] == "computer_control"
    assert params["tool_name"] == "execute_command"
    assert params["command"] == "echo hello"


def test_registry_normalizes_full_mcp_tool_id():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "computer_control",
                    "available_tools": [{"name": "write_file"}],
                }
            ]
        }
    )

    tool_name, params = registry.normalize_call(
        tool_name="computer_control.write_file",
        params={"path": "notes.txt", "content": "x"},
    )

    assert tool_name == "computer_control.write_file"
    assert params["agentType"] == "mcp"
    assert params["service_name"] == "computer_control"
    assert params["tool_name"] == "write_file"


def test_registry_normalizes_service_wrapped_mcp_action():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "content_tools",
                    "available_tools": [{"name": "web_fetch"}],
                }
            ]
        }
    )

    tool_name, params = registry.normalize_call(
        tool_name="content_tools",
        params={
            "agentType": "mcp",
            "service_name": "content_tools",
            "tool_name": "web_fetch",
            "url": "https://www.news.cn/",
        },
    )

    assert tool_name == "content_tools.web_fetch"
    assert params["service_name"] == "content_tools"
    assert params["tool_name"] == "web_fetch"
