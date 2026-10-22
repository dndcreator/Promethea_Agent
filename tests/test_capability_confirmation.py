import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentkit.security.approval import approval_scope
from gateway.action.service import ActionService
from gateway.capability_service import CapabilityService, ToolInvocationContext, ToolPolicyViolationError
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.tools.spec import ToolSource
from gateway.workflow_engine import WorkflowEngine


def _runtime(source="extension", effect="external_write"):
    invoke = AsyncMock(return_value={"ok": True})
    manager = SimpleNamespace(
        get_available_services_filtered=lambda: {"mcp_services": [{
            "name": "risky", "available_tools": [{"name": "run", "side_effect_level": effect}],
        }]} if source == "mcp" else {"mcp_services": []},
        call_service_tool=invoke,
    )
    hook = AsyncMock()
    emitter = EventEmitter()
    events = []

    async def record(event):
        events.append(event)

    emitter.on(EventType.TOOL_CALL_START, record)
    emitter.on(EventType.TOOL_CALL_ERROR, record)
    service = CapabilityService(
        mcp_manager=manager, event_emitter=emitter,
        hook_manager=SimpleNamespace(before_tool_call=hook),
    )
    if source != "mcp":
        service.register_tool(SimpleNamespace(
            tool_id="risky.run", name="risky.run", description="Perform an operation",
            side_effect_level=effect, tool_source=ToolSource(source), invoke=invoke,
        ))
    return service, invoke, hook, events


@pytest.mark.parametrize("source", ["local", "extension", "mcp"])
@pytest.mark.parametrize("effect", ["external_write", "privileged_host_action"])
@pytest.mark.asyncio
async def test_unconfirmed_effect_is_blocked_before_hooks_or_dispatch(source, effect):
    service, invoke, hook, events = _runtime(source, effect)
    with pytest.raises(ToolPolicyViolationError) as caught:
        await service.call_tool("risky.run", {"value": 1})
    assert caught.value.code == "TOOL_CONFIRMATION_REQUIRED"
    invoke.assert_not_awaited()
    hook.assert_not_awaited()
    assert not any(event.event == EventType.TOOL_CALL_START for event in events)
    assert events[-1].payload["error_detail"]["code"] == "TOOL_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("source", ["local", "extension", "mcp"])
@pytest.mark.asyncio
async def test_exact_scoped_confirmation_allows_one_dispatch(source):
    service, invoke, _, _ = _runtime(source)
    with approval_scope("risky.run", {"value": 1}, confirmed=True):
        assert await service.call_tool("risky.run", {"value": 1}) == {"ok": True}
        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool("risky.run", {"value": 1})
        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool("risky.run", {"value": 2, "approved": True})
    invoke.assert_awaited_once()
    with pytest.raises(ToolPolicyViolationError):
        await service.call_tool("risky.run", {"value": 1})


@pytest.mark.parametrize("origin", ["reasoning", "workflow", "scheduler", "managed_runtime", "http"])
@pytest.mark.asyncio
async def test_invocation_origin_or_forged_metadata_cannot_grant_consent(origin):
    service, invoke, _, _ = _runtime()
    context = ToolInvocationContext(source=origin, user_id="alice", metadata={"approved": True})
    with pytest.raises(ToolPolicyViolationError):
        await service.call_tool("risky.run", {"approved": True}, ctx=context)
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_never_overrides_explicit_policy_denial():
    service, invoke, _, _ = _runtime()
    with approval_scope("risky.run", {}, confirmed=True):
        with pytest.raises(ToolPolicyViolationError, match="denylist"):
            await service.call_tool("risky.run", {}, user_config={"tools": {"deny": ["risky.run"]}})
    invoke.assert_not_awaited()


@pytest.mark.parametrize("effect", ["read_only", "workspace_write"])
@pytest.mark.asyncio
async def test_lower_risk_operations_keep_existing_policy(effect):
    service, invoke, _, _ = _runtime(effect=effect)
    assert await service.call_tool("risky.run", {}) == {"ok": True}
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_approved_wrapper_cannot_authorize_a_nested_high_risk_tool():
    service, invoke, _, events = _runtime()

    async def nested(args, ctx):
        return await service.call_tool("risky.run", args)

    service.register_tool(SimpleNamespace(
        tool_id="wrapper.run", name="wrapper.run", description="Delegate an operation",
        side_effect_level="external_write", invoke=nested,
    ))
    with approval_scope("wrapper.run", {"value": 1}, confirmed=True):
        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool("wrapper.run", {"value": 1})
    invoke.assert_not_awaited()
    assert {event.payload["tool_id"] for event in events if event.event == EventType.TOOL_CALL_ERROR} == {
        "risky.run", "wrapper.run",
    }


@pytest.mark.asyncio
async def test_confirmation_must_still_be_active_after_async_authorization(monkeypatch):
    service, invoke, _, _ = _runtime()
    reached = asyncio.Event()
    resume = asyncio.Event()
    original = service._authorize_tool_call

    async def delayed(**kwargs):
        result = await original(**kwargs)
        reached.set()
        await resume.wait()
        return result

    monkeypatch.setattr(service, "_authorize_tool_call", delayed)
    with approval_scope("risky.run", {}, confirmed=True):
        task = asyncio.create_task(service.call_tool("risky.run", {}))
        await reached.wait()
    resume.set()
    with pytest.raises(ToolPolicyViolationError):
        await task
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_is_rechecked_after_awaited_hooks():
    service, invoke, hook, events = _runtime()
    reached, resume = asyncio.Event(), asyncio.Event()

    async def delay(_payload):
        reached.set()
        await resume.wait()

    hook.side_effect = delay
    with approval_scope("risky.run", {}, confirmed=True):
        task = asyncio.create_task(service.call_tool("risky.run", {}))
        await reached.wait()
    resume.set()
    with pytest.raises(ToolPolicyViolationError):
        await task
    invoke.assert_not_awaited()
    assert sum(event.event == EventType.TOOL_CALL_ERROR for event in events) == 1


@pytest.mark.asyncio
async def test_hook_argument_changes_do_not_inherit_original_confirmation():
    service, invoke, hook, _ = _runtime()

    async def change(payload):
        payload["params"]["target"]["value"] = "changed"

    hook.side_effect = change
    args = {"target": {"value": "original"}}
    with approval_scope("risky.run", args, confirmed=True):
        with pytest.raises(ToolPolicyViolationError):
            await service.call_tool("risky.run", args)
    assert args == {"target": {"value": "original"}}
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_registry_normalization_keeps_exact_raw_call_confirmation():
    service, invoke, _, _ = _runtime("mcp")
    with approval_scope("run", {"value": 1}, confirmed=True):
        assert await service.call_tool("run", {"value": 1}) == {"ok": True}
    invoke.assert_awaited_once_with(service_name="risky", tool_name="run", args={"value": 1})


@pytest.mark.asyncio
async def test_workflow_direct_tool_bridge_cannot_skip_confirmation(tmp_path):
    service, invoke, _, _ = _runtime()
    engine = WorkflowEngine(capability_service=service, storage_path=str(tmp_path / "workflow.json"))
    with pytest.raises(ToolPolicyViolationError):
        await engine.run_tool_action(
            workflow_run_id=None, session_id="s", user_id="alice",
            tool_type="extension", service_name="risky", tool_name="run", args={"value": 1},
        )
    invoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["extension", "mcp"])
async def test_action_loop_confirmation_still_resumes_the_real_runtime(source):
    service, invoke, _, _ = _runtime(source)
    responses = iter([
        json.dumps({"action": "tool_calls", "calls": [
            {"id": "one", "tool_name": "risky.run", "args": {"value": 1}},
            {"id": "two", "tool_name": "risky.run", "args": {"value": 2}},
        ]}),
        json.dumps({"action": "answer", "content": "Done"}),
    ])
    core = SimpleNamespace(call_llm=AsyncMock(side_effect=lambda *a, **k: {"status": "success", "content": next(responses)}))
    action = ActionService(conversation_core=core)
    pending = await action.run_action(
        goal="Perform an operation", messages=[{"role": "user", "content": "Proceed"}],
        tool_executor=service.call_tool, confirmation_resolver=service.requires_confirmation, budget=3,
    )
    assert pending["status"] == "needs_confirmation"
    invoke.assert_not_awaited()
    second = await action.resume_action(
        pending=pending, approved_call_id="one", session_id=None, user_id=None,
        run_context=None, user_config=None, tool_executor=service.call_tool,
        confirmation_resolver=service.requires_confirmation,
    )
    assert second["status"] == "needs_confirmation"
    assert second["tool_call_id"] == "two"
    invoke.assert_not_awaited()
    result = await action.resume_action(
        pending=second, approved_call_id="two", session_id=None, user_id=None,
        run_context=None, user_config=None, tool_executor=service.call_tool,
        confirmation_resolver=service.requires_confirmation,
    )
    assert result["status"] == "success"
    assert invoke.await_count == 2


@pytest.mark.asyncio
async def test_gateway_direct_tool_request_exposes_structured_confirmation_error():
    from gateway.server import GatewayServer
    from gateway.protocol import RequestType

    service, invoke, _, _ = _runtime("mcp")
    server = GatewayServer()
    server.capability_service = service
    result = await server.handle_http_request(
        method=RequestType.TOOL_CALL, user_id="alice",
        params={"tool_name": "risky.run", "params": {"approved": True}},
    )
    assert result.ok is False
    assert result.error_detail.code == "TOOL_CONFIRMATION_REQUIRED"
    assert result.error_detail.retryable is False
    assert result.error_detail.details["requires_confirmation"] is True
    invoke.assert_not_awaited()
