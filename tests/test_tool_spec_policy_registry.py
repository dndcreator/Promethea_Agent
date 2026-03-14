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


def test_side_effect_tool_denied_by_default_without_explicit_allow():
    policy = ToolPolicy()
    spec = ToolSpec(
        tool_name="write_file",
        service_name="computer_control",
        source=ToolSource.MCP,
        side_effect_level=SideEffectLevel.WORKSPACE_WRITE,
    )
    run_context = SimpleNamespace(tool_policy={})

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
