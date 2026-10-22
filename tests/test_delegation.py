import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentkit.security.approval import approval_scope, call_is_approved
from agentkit.tools.subagent import DelegateTool
from config import config
from gateway.capability_service import CapabilityService, ToolInvocationContext, ToolPolicyViolationError
from gateway.conversation_service import ConversationService
from gateway.delegation import DelegationRequest, DelegationRuntime, current_delegation
from gateway.events import EventEmitter
from gateway.models.run_context import RunContext
from gateway.models.session_state import SessionState
from gateway.protocol import EventType
from gateway.runtime_event_log import RuntimeEventLog
from gateway.workbench_projection import WorkbenchProjection


def context(enabled=True):
    return RunContext(
        request_id="request", trace_id="trace", conversation_turn_id="parent-turn",
        action_loop_id="parent-action", input_payload={"metadata": {"multi_agent": enabled}},
        session_state=SessionState(session_id="session", user_id="alice", trace_id="trace"),
    )


def capabilities():
    service = CapabilityService(mcp_manager=SimpleNamespace(get_available_services_filtered=lambda: {"mcp_services": []}))
    service._tool_discovery_initialized = True
    service.register_tool(SimpleNamespace(
        tool_id="test.read", name="test.read", description="read", input_schema={"type": "object"},
        side_effect_level="read_only", invoke=AsyncMock(return_value={"value": 1}),
    ))
    service.register_tool(SimpleNamespace(
        tool_id="test.write", name="test.write", description="write", input_schema={"type": "object"},
        side_effect_level="external_write", invoke=AsyncMock(return_value={"ok": True}),
    ))
    return service


def request(label="research", **kwargs):
    return DelegationRequest(objective="inspect independent material", label=label, run_in_background=False, **kwargs)


@pytest.mark.asyncio
async def test_parallel_children_are_isolated_and_results_keep_identity():
    runtime = DelegationRuntime()
    parent = context()
    parent.reasoning_state = {"private": "parent transcript"}
    capability = capabilities()
    entered = []
    release = asyncio.Event()

    async def run(**kwargs):
        child = kwargs["run_context"]
        assert child is not parent and child.session_state is not parent.session_state
        assert child.reasoning_state == {} and "private" not in str(child.input_payload)
        assert child.conversation_turn_id != parent.conversation_turn_id
        assert current_delegation().depth == 1
        assert kwargs["user_config"]["action"]["gaps"]["enabled"] is False
        entered.append(child.conversation_turn_id)
        if len(entered) == 2:
            release.set()
        await asyncio.wait_for(release.wait(), 2)
        return {"status": "success", "content": kwargs["label"]}

    conversation = SimpleNamespace(capability_service=capability, run_delegated_turn=run)
    with runtime.turn():
        results = await asyncio.gather(*(runtime.delegate(conversation, request(label), parent=parent, user_config={}) for label in ("A", "B")))
    assert [item["output"] for item in results] == ["A", "B"]
    assert len(set(entered)) == 2 and all(item["ok"] for item in results)
    assert runtime._active == 0 and current_delegation() is None
    assert parent.reasoning_state == {"private": "parent transcript"}


@pytest.mark.asyncio
async def test_disabled_direct_call_and_forged_scope_do_not_start_children(monkeypatch):
    runtime = DelegationRuntime()
    conversation = SimpleNamespace(capability_service=capabilities(), run_delegated_turn=AsyncMock())
    with runtime.turn():
        with pytest.raises(PermissionError):
            await runtime.delegate(conversation, request(), parent=context(False), user_config={})
        monkeypatch.setattr(config.multi_agent, "enabled", False)
        with pytest.raises(PermissionError):
            await runtime.delegate(conversation, request(), parent=context(), user_config={"multi_agent": {"enabled": True}})
    conversation.run_delegated_turn.assert_not_awaited()
    with pytest.raises(PermissionError):
        await runtime.delegate(conversation, request(), parent=context(), user_config={})


@pytest.mark.asyncio
async def test_parent_tools_are_an_upper_bound_and_approval_never_inherits():
    runtime = DelegationRuntime()
    capability = capabilities()

    async def run(**kwargs):
        child = kwargs["run_context"]
        assert await capability.call_tool("test.read", {}, run_context=child) == {"value": 1}
        # Even an independently minted matching grant cannot elevate a delegated child.
        with approval_scope("test.write", {}, confirmed=True):
            with pytest.raises(ToolPolicyViolationError):
                await capability.call_tool("test.write", {}, run_context=child)
            with pytest.raises(ToolPolicyViolationError):
                await capability.call_tool("test.write", {}, user_config={"tools": {"allow": ["*"]}})
        return {"status": "success", "content": "done"}

    conversation = SimpleNamespace(capability_service=capability, run_delegated_turn=run)
    with runtime.turn():
        with pytest.raises(PermissionError):
            await runtime.delegate(conversation, request(tools=["unavailable.run"]), parent=context(), user_config={})
        result = await runtime.delegate(conversation, request(tools=["test.read"]), parent=context(), user_config={})
    assert result["ok"]
    capability._registered_tools["test.write"].invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_child_tool_subset_is_enforced_even_without_context_or_with_wider_config():
    runtime = DelegationRuntime()
    capability = capabilities()

    async def run(**kwargs):
        with pytest.raises(ToolPolicyViolationError, match="scope"):
            await capability.call_tool("test.read", {}, user_config={"tools": {"allow": ["*"]}})
        return {"status": "success", "content": "done"}

    conversation = SimpleNamespace(capability_service=capability, run_delegated_turn=run)
    with runtime.turn():
        result = await runtime.delegate(conversation, request(tools=[]), parent=context(), user_config={})
    assert result["ok"]
    capability._registered_tools["test.read"].invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_is_shared_across_parent_turns_and_failure_releases_slots(monkeypatch):
    runtime = DelegationRuntime()
    entered = asyncio.Event()
    release = asyncio.Event()
    monkeypatch.setattr(config.multi_agent, "max_parallel", 1)

    async def run(**kwargs):
        entered.set()
        await release.wait()
        raise RuntimeError("synthetic infrastructure failure")

    conversation = SimpleNamespace(capability_service=capabilities(), run_delegated_turn=run)

    async def parent_turn():
        with runtime.turn():
            await runtime.delegate(conversation, request(), parent=context(), user_config={})

    task = asyncio.create_task(parent_turn())
    await entered.wait()
    try:
        with runtime.turn():
            with pytest.raises(PermissionError, match="capacity"):
                await runtime.delegate(conversation, request(), parent=context(), user_config={"multi_agent": {"max_parallel": 8}})
    finally:
        release.set()
        with pytest.raises(RuntimeError, match="synthetic"):
            await task
    assert runtime._active == 0


@pytest.mark.asyncio
async def test_cancellation_and_timeout_join_children_and_release_capacity(monkeypatch):
    runtime = DelegationRuntime()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def run(**kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    conversation = SimpleNamespace(capability_service=capabilities(), run_delegated_turn=run)
    with runtime.turn():
        task = asyncio.create_task(runtime.delegate(conversation, request(), parent=context(), user_config={}))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and runtime._active == 0
        monkeypatch.setattr(config.multi_agent, "timeout_s", 1)
        result = await runtime.delegate(conversation, request(), parent=context(), user_config={})
        assert result["status"] == "timed_out" and result["ok"] is False
    assert runtime._active == 0


@pytest.mark.asyncio
async def test_depth_turn_budget_and_parallel_capacity(monkeypatch):
    runtime = DelegationRuntime()
    capability = capabilities()
    conversation = SimpleNamespace(capability_service=capability)

    async def run(**kwargs):
        with pytest.raises(PermissionError, match="depth"):
            await runtime.delegate(conversation, request(), parent=kwargs["run_context"], user_config={})
        return {"status": "success", "content": "done"}

    conversation.run_delegated_turn = run
    monkeypatch.setattr(config.multi_agent, "max_children", 1)
    with runtime.turn():
        assert (await runtime.delegate(conversation, request(), parent=context(), user_config={}))["ok"]
        with pytest.raises(PermissionError, match="budget"):
            await runtime.delegate(conversation, request(), parent=context(), user_config={})
    assert runtime._active == 0


@pytest.mark.asyncio
async def test_real_child_uses_existing_action_machine_no_parent_history_or_learning():
    events = EventEmitter()
    calls = []

    class Core:
        async def call_llm(self, messages, **kwargs):
            assert not call_is_approved()
            calls.append(messages)
            return {"status": "success", "content": json.dumps({"action": "answer", "content": "child findings"}), "usage": {"completion_tokens": 8}}

    capability = capabilities()
    conversation = ConversationService(conversation_core=Core(), capability_service=capability, event_emitter=events)
    conversation._get_user_prompt_and_config = AsyncMock(return_value=("Core identity", {}))
    conversation._record_action_episode = AsyncMock()
    with conversation.delegation.turn(), approval_scope("outer", {}, confirmed=True):
        result = await conversation.delegation.delegate(conversation, request(tools=[]), parent=context(), user_config={})
    assert result["output"] == "child findings" and result["action_loop_id"].startswith("act_")
    assert len(calls) == 1 and "parent transcript" not in str(calls)
    conversation._record_action_episode.assert_not_awaited()
    child_events = [event for event in events.get_history() if event.event == EventType.ACTION_STATE_CHANGED]
    assert child_events and all(event.payload["parent_action_loop_id"] == "parent-action" for event in child_events)


@pytest.mark.asyncio
async def test_child_retains_task_execution_guard_without_committing_parent_gaps():
    class Core:
        async def call_llm(self, messages, **kwargs):
            return {"status": "success", "content": json.dumps({"action": "answer", "content": "findings", "gap_update": {"add": []}})}

    conversation = ConversationService(conversation_core=Core(), capability_service=capabilities())
    conversation._get_user_prompt_and_config = AsyncMock(return_value=("Core identity", {}))
    task = SimpleNamespace(
        get_task=Mock(return_value={"objective": "root objective", "goal_gaps": {}}),
        assert_action_execution=Mock(), commit_goal_gaps=Mock(),
    )
    conversation.action_service.task_service = task
    parent = context()
    parent.task_id = "task"
    parent.task_run_id = "task-run"
    parent.execution_token = {"epoch": 2}
    with conversation.delegation.turn():
        result = await conversation.delegation.delegate(conversation, request(), parent=parent, user_config={})
    assert result["ok"]
    assert task.assert_action_execution.call_count > 0
    assert task.assert_action_execution.call_args.kwargs["execution_token"] == {"epoch": 2}
    task.commit_goal_gaps.assert_not_called()
    assert parent.goal_gaps == {} and parent.action_loop_id == "parent-action"


@pytest.mark.asyncio
async def test_persisted_child_events_are_recovered_under_ancestor_run(tmp_path):
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter(event_log=log)
    await emitter.emit(EventType.ACTION_STATE_CHANGED, {
        "user_id": "alice", "session_id": "session", "action_loop_id": "grandchild-action",
        "parent_action_loop_id": "child-action", "ancestor_action_loop_ids": ["parent-action", "child-action"],
        "status": "completed",
    })
    recovered = WorkbenchProjection(task_service=None, workflow_engine=None, event_log=RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl")))
    rows = recovered._query_events(user_id="alice", session_id="session", run_id="parent-action")
    assert len(rows) == 1 and rows[0]["payload"]["action_loop_id"] == "grandchild-action"
    assert recovered._query_events(user_id="bob", session_id="session", run_id="parent-action") == []


@pytest.mark.asyncio
async def test_registered_delegate_is_disabled_by_runtime_without_run_option():
    capability = capabilities()
    delegate = DelegateTool(SimpleNamespace(conversation_service=AsyncMock()))
    capability.register_tool(delegate)
    with pytest.raises(ToolPolicyViolationError):
        await capability.call_tool(delegate.tool_id, request().model_dump(), run_context=context(False))
    assert capability.inspect_capabilities([delegate.tool_id], run_context=context(False))["items"][0]["callable_now"] is False


@pytest.mark.asyncio
async def test_parent_model_delegates_through_registry_and_synthesizes_from_observation():
    capability = capabilities()
    emitter = EventEmitter()
    child_calls = []

    class Core:
        async def call_llm(self, messages, **kwargs):
            scope = current_delegation()
            if scope and scope.depth:
                child_calls.append(messages)
                assert "parent-only history" not in str(messages)
                content = {"action": "answer", "content": "independent finding"}
            elif messages[-1]["content"] == "parent-only history":
                content = {"action": "tool_calls", "calls": [{"id": "delegate-1", "name": "subagent.delegate", "args": request().model_dump()}]}
            else:
                observation = json.loads(messages[-1]["content"][0]["text"])
                assert observation["result"]["output"] == "independent finding"
                content = {"action": "answer", "content": "parent synthesis", "evidence_refs": [observation["observation_id"]]}
            return {"status": "success", "content": json.dumps(content), "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

    conversation = ConversationService(conversation_core=Core(), capability_service=capability, event_emitter=emitter)
    conversation._get_user_prompt_and_config = AsyncMock(return_value=("Core identity", {}))
    conversation._record_action_episode = AsyncMock()
    capability.register_tool(DelegateTool(SimpleNamespace(conversation_service=conversation)))
    parent = context()

    async def execute(name, args):
        return await capability.call_tool(name, args, run_context=parent, ctx=ToolInvocationContext(
            user_id="alice", session_id="session", metadata={"run_context": parent, "user_config": {}},
        ))

    result = await conversation.run_chat_loop(
        [{"role": "user", "content": "parent-only history"}], user_config={},
        user_id="alice", session_id="session", run_context=parent, tool_executor=execute,
    )
    assert result["content"] == "parent synthesis" and len(child_calls) == 1
    assert result["observations"][0]["tool_name"] == "subagent.delegate"
    assert result["usage"]["prompt_tokens"] == 9 and result["usage"]["completion_tokens"] == 6
    conversation._record_action_episode.assert_awaited_once()


@pytest.mark.asyncio
async def test_settled_child_cannot_leave_usable_tool_authority_in_background():
    runtime = DelegationRuntime()
    capability = capabilities()
    release = asyncio.Event()
    late = []

    async def run(**kwargs):
        async def detached():
            await release.wait()
            with pytest.raises(ToolPolicyViolationError, match="settled"):
                await capability.call_tool("test.read", {})
        late.append(asyncio.create_task(detached()))
        return {"status": "success", "content": "done"}

    conversation = SimpleNamespace(capability_service=capability, run_delegated_turn=run)
    with runtime.turn():
        await runtime.delegate(conversation, request(), parent=context(), user_config={})
        release.set()
        await asyncio.gather(*late)
    capability._registered_tools["test.read"].invoke.assert_not_awaited()


@pytest.mark.parametrize("operation", ["resume_action", "reject_pending_action"])
@pytest.mark.asyncio
async def test_confirmation_resume_retains_delegation_switch_and_spent_budget(operation):
    async def resume(**kwargs):
        scope = current_delegation()
        assert scope.depth == 0 and scope.budget.count == 4
        assert kwargs["run_context"].input_payload["metadata"]["multi_agent"] is True
        return {"status": "needs_confirmation"}

    action = SimpleNamespace(**{operation: resume})
    conversation = ConversationService(conversation_core=SimpleNamespace(), action_service=action)
    conversation._record_action_episode = AsyncMock()
    kwargs = dict(pending={"delegation_checkpoint": {"spent": 4, "enabled": True}}, user_config={}, session_id="session", user_id="alice", run_context=context(False), tool_executor=None)
    if operation == "resume_action":
        kwargs["approved_call_id"] = "call-1"
    result = await getattr(conversation, operation)(**kwargs)
    assert result["delegation_checkpoint"] == {"spent": 4, "enabled": True}
    assert current_delegation() is None
