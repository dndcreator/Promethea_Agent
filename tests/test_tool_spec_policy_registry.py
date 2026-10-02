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
        tool_name="lookup",
        service_name="catalog",
        description="look up a catalog entry",
        source=ToolSource.MCP,
    )
    assert spec.full_name == "catalog.lookup"
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
        tool_name="lookup",
        service_name="catalog",
        source=ToolSource.MCP,
        side_effect_level=SideEffectLevel.READ_ONLY,
    )
    run_context = SimpleNamespace(tool_policy={"deny": {"catalog.lookup"}})

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
                    "name": "catalog",
                    "description": "catalog tools",
                    "available_tools": [
                        {"name": "lookup", "description": "look up entries"},
                        {"name": "list", "description": "list entries"},
                    ],
                }
            ]
        }
    )

    spec = registry.resolve(tool_name="catalog", params={"service_name": "catalog", "tool_name": "lookup"})
    assert spec.full_name == "catalog.lookup"
    assert spec.source == ToolSource.MCP


def test_mcp_registry_preserves_manifest_config_requirement():
    registry = ToolRegistry()
    requirement = {"path": "feature.enabled", "equals": True}
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "optional",
                    "available_tools": [
                        {"name": "run", "description": "run", "requires_config": requirement}
                    ],
                }
            ]
        }
    )
    spec = registry.resolve(tool_name="optional.run", params={})
    assert spec.metadata["requires_config"] == requirement


def test_mcp_registry_preserves_private_tool_owner():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "private_tool",
                    "available_tools": [
                        {"name": "run", "description": "run", "owner_user_id": "u1"}
                    ],
                }
            ]
        }
    )
    spec = registry.resolve(tool_name="private_tool.run", params={})
    assert spec.metadata["owner_user_id"] == "u1"


def test_manifest_side_effect_selector_resolves_per_action():
    registry = ToolRegistry()
    registry.register_mcp_services(
        {
            "mcp_services": [
                {
                    "name": "computer",
                    "available_tools": [
                        {
                            "name": "screen_action",
                            "side_effect_level": "privileged_host_action",
                            "side_effect_selector": {
                                "parameter": "action",
                                "default": "privileged_host_action",
                                "groups": {"read_only": ["screenshot"]},
                            },
                        }
                    ],
                }
            ]
        }
    )

    observed = registry.resolve_for_call(
        tool_name="computer.screen_action",
        params={"action": "screenshot"},
    )
    mutated = registry.resolve_for_call(
        tool_name="computer.screen_action",
        params={"action": "click"},
    )
    assert observed.side_effect_level == SideEffectLevel.READ_ONLY
    assert mutated.side_effect_level == SideEffectLevel.PRIVILEGED_HOST_ACTION


def test_undeclared_tool_risk_fails_closed_without_name_heuristics():
    registry = ToolRegistry()
    spec = registry.resolve(
        tool_name="unknown.harmless_sounding_name",
        params={"service_name": "unknown", "tool_name": "harmless_sounding_name"},
    )
    assert spec.side_effect_level == SideEffectLevel.PRIVILEGED_HOST_ACTION
    assert spec.metadata["risk_metadata_missing"] is True


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
