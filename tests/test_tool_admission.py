"""Unknown/unavailable operations return facts, never phantom approval requests."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentkit.security.approval import approval_scope
from gateway.action import ActionService
from gateway.capability_service import CapabilityService
from gateway.tools.registry import ToolNotFoundError
from tests.test_model_protocol import core, packet


def runtime(**kwargs):
    service = CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}), **kwargs)
    service._tool_discovery_initialized = True
    invoke = AsyncMock(return_value={"sent": True})
    service.register_tool(SimpleNamespace(tool_id="fixture.send", description="Send", invoke=invoke,
        side_effect_level="external_write", input_schema={"type": "object"}))
    return service, invoke


@pytest.mark.asyncio
@pytest.mark.parametrize("condition,code", [("unknown", "TOOL_NOT_FOUND"), ("disabled", "CAPABILITY_UNAVAILABLE"),
    ("configuration", "TOOL_POLICY_DENIED"), ("dependency", "CAPABILITY_UNAVAILABLE"),
    ("owner", "TOOL_POLICY_DENIED"), ("deny", "TOOL_POLICY_DENIED")])
async def test_confirmation_and_dispatch_share_admission_even_with_an_approval(condition, code):
    service, invoke = runtime(capability_provider=lambda: {"screen": {"initialized": False}})
    spec = service.tool_registry.resolve(tool_name="fixture.send", params={})
    config, name = {}, "fixture.send"
    if condition == "unknown":
        name = "missing.operation"
    elif condition == "disabled":
        spec = spec.model_copy(update={"enabled": False})
    elif condition == "configuration":
        spec.metadata["requires_config"] = "feature.enabled"
    elif condition == "dependency":
        spec.metadata["requires_capability"] = "computer.screen"
    elif condition == "owner":
        spec.metadata["owner_user_id"] = "bob"
    else:
        config = {"tools": {"deny": [name]}}
    service.tool_registry.register_spec(spec)
    context = SimpleNamespace(user_id="alice", session_id="s")
    before = service.tool_registry.list_specs()
    with pytest.raises(Exception) as confirmation:
        service.requires_confirmation(name, {}, run_context=context, user_config=config)
    assert confirmation.value.code == code
    with approval_scope(name, {}, confirmed=True):
        with pytest.raises(Exception) as execution:
            await service.call_tool(name, {}, run_context=context, user_config=config)
    assert execution.value.code == code
    invoke.assert_not_called()
    assert service.tool_registry.list_specs() == before


def test_inspecting_missing_names_does_not_pollute_the_catalog():
    service, _ = runtime()
    before = service.tool_registry.list_specs()
    result = service.inspect_capabilities(["capability_inspect", "arbitrary.absent"])
    assert all(not row["registered"] and not row["callable_now"] and not row["requires_confirmation"] for row in result["items"])
    assert service.tool_registry.list_specs() == before
    with pytest.raises(ToolNotFoundError):
        service.tool_registry.resolve(tool_name="agent.unknown", params={"agentType": "agent", "agent_name": "unknown"})
    assert service.tool_registry.list_specs() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["capability_inspect", "arbitrary.absent"])
@pytest.mark.parametrize("unknown_first", [False, True])
async def test_whole_batch_is_checked_before_waiting_for_any_approval(monkeypatch, missing, unknown_first):
    calls = [{"id": "send", "tool_name": "fixture.send", "args": {}},
             {"id": "missing", "tool_name": missing, "args": {}}]
    if unknown_first:
        calls.reverse()
    conv, requests = core(monkeypatch, [packet("tool_calls", {"calls": calls}, "batch"),
        packet("capability_inspect", {"capability_names": ["fixture.send"]}, "inspect"),
        {"role": "assistant", "content": "No operation executed; the invalid name was corrected."}])
    service, invoke = runtime()
    out = await ActionService(conversation_core=conv, capability_service=service).run_action(goal="send", messages=[],
        tool_executor=service.call_tool, confirmation_resolver=service.requires_confirmation,
        capability_inspector=_inspector(service), budget=3)
    assert out["status"] == "success" and len(requests) == 3
    assert not any(row["to"] == "waiting_confirmation" for row in out["action_state_transitions"])
    errors = {row["tool_call_id"]: row["error"]["code"] for row in out["observations"][:2]}
    assert errors == {"send": "BATCH_NOT_EXECUTED", "missing": "TOOL_NOT_FOUND"}
    assert out["observations"][2]["ok"] is True
    receipt = next(row for row in requests[1]["messages"] if row.get("tool_call_id") == "batch")
    assert len(json.loads(receipt["content"])["observations"]) == 2
    assert [spec.full_name for spec in service.tool_registry.list_specs()] == ["fixture.send"]
    invoke.assert_not_called()


def _inspector(service):
    async def inspect(names):
        return service.inspect_capabilities(names)
    return inspect


@pytest.mark.asyncio
@pytest.mark.parametrize("removed", [False, True])
async def test_approval_restart_revalidates_changed_registry(monkeypatch, removed):
    conv, _ = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.send", "args": {}}, "send"),
                               {"role": "assistant", "content": "The approved tool is no longer available."}])
    service, invoke = runtime()
    options = dict(user_id="alice", session_id="s", user_config=None, run_context=None,
                   tool_executor=service.call_tool, confirmation_resolver=service.requires_confirmation)
    pending = await ActionService(conversation_core=conv, capability_service=service).run_action(goal="send", messages=[], **options)
    assert pending["status"] == "needs_confirmation"
    if removed:
        service.unregister_tool("fixture.send")
    else:
        spec = service.tool_registry.resolve(tool_name="fixture.send", params={})
        service.tool_registry.register_spec(spec.model_copy(update={"enabled": False}))
    out = await ActionService(conversation_core=conv, capability_service=service).resume_action(
        pending=json.loads(json.dumps(pending)), approved_call_id="send", **options)
    assert out["status"] == "success" and out["observations"][0]["ok"] is False
    assert out["observations"][0]["error"]["code"] == ("TOOL_NOT_FOUND" if removed else "CAPABILITY_UNAVAILABLE")
    assert out["execution_path"][0]["executed"] is False
    invoke.assert_not_called()
