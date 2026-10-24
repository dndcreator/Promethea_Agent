import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channels.delivery_runtime import ChannelDeliveryRuntime
from channels.delivery_store import DeliveryStore
from channels.runtime_lock import RuntimeLock
from channels.settings import ChannelSettings, GroupBinding
from channels.webhook_channel import ProviderRejected
from gateway.http.identity_store import IdentityStore
from gateway.protocol import GatewayProtocol, RequestType
from tests.test_bot_channels import qq, payload, signed
from tests.test_identity_store import _legacy_user


def host(tmp_path, *, response=None, queue_limit=200):
    identities = IdentityStore(tmp_path / "identities.sqlite3")
    for name in ("alice", "bob", "group"):
        identities.create(_legacy_user(name, name))
    channel = qq()
    identities.bind_channel("alice", "qq:app1", "external1")
    manager = SimpleNamespace(get_pending_confirmation=lambda *a, **kw: None)
    server = SimpleNamespace(channels={"qq": channel}, message_manager=manager, handle_http_request=AsyncMock(return_value=response or GatewayProtocol.create_response("r1", True, {"response_text": "模型的真实回复"})))
    runtime = ChannelDeliveryRuntime(server=server, identities=identities, settings=ChannelSettings(_env_file=None, queue_limit=queue_limit), path=tmp_path / "delivery.sqlite3")
    channel.send_text = AsyncMock(return_value={"success": True, "message_id": "sent1"})
    runtime.start()
    return runtime, channel, identities, server


async def settled(runtime):
    for _ in range(300):
        await asyncio.sleep(0.01)
        states = [row["state"] for row in runtime.store.list_user("alice") + runtime.store.list_user("bob") + runtime.store.list_user("group")]
        if states and all(state not in {"queued", "processing", "ready", "delivering"} for state in states):
            return
    raise AssertionError("transport did not settle")


@pytest.mark.asyncio
async def test_signed_message_uses_existing_gateway_identity_session_and_persisted_dedup(tmp_path):
    runtime, channel, identities, server = host(tmp_path)
    value = payload()
    try:
        assert await runtime.receive("qq", *signed(channel, value)) == {"op": 12, "d": 0}
        await settled(runtime)
        row = runtime.store.list_user("alice")[0]
        assert row["state"] == "delivered" and row["execution_status"] == "completed"
        request = server.handle_http_request.await_args.kwargs
        assert request["method"] == RequestType.CHAT and request["user_id"] == "alice"
        assert request["retries"] == 0 and request["params"]["session_id"] == row["session_id"]
        assert channel.send_text.await_args.args == ("external1", "模型的真实回复")
        assert channel.send_text.await_args.kwargs["reply_to"] == "m1"
        await runtime.receive("qq", *signed(channel, value))
        assert server.handle_http_request.await_count == 1
        assert runtime.store.list_user("bob") == []
        await runtime.stop()
        recovered = ChannelDeliveryRuntime(server=server, identities=identities, settings=runtime.settings, path=runtime.store.path)
        recovered.start()
        try:
            await recovered.receive("qq", *signed(channel, value))
            assert server.handle_http_request.await_count == 1
        finally:
            await recovered.stop()
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_proof_pairing_never_enters_model_or_transcript_and_cannot_be_stolen(tmp_path):
    runtime, channel, identities, server = host(tmp_path)
    try:
        command = identities.issue_channel_pairing("bob", "qq:app1")["command"]
        value = payload(command, "pair", sender="external2")
        await runtime.receive("qq", *signed(channel, value))
        await settled(runtime)
        assert identities.get_by_channel("qq:app1", "external2")["user_id"] == "bob"
        assert server.handle_http_request.await_count == 0
        saved = runtime.store.get(runtime.store.list_user("bob")[0]["delivery_id"])
        assert command not in saved["envelope"] and command not in saved["response"]
        assert identities.consume_channel_pairing(command[6:], "qq:app1", "external3") is None
        await runtime.receive("qq", *signed(channel, value))
        assert len(runtime.store.list_user("bob")) == 1
        identities.unbind_channel("bob", "qq:app1")
        assert identities.consume_channel_pairing(command[6:], "qq:app1", "external2") is None
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_group_has_explicit_allowed_senders_and_cannot_use_personal_identity(tmp_path):
    runtime, channel, _, server = host(tmp_path)
    try:
        await runtime.receive("qq", *signed(channel, payload("group", "a", group=True)))
        assert server.handle_http_request.await_count == 0
        channel.settings.groups["g1"] = GroupBinding(user_id="alice", allowed_senders=["external1"])
        await runtime.receive("qq", *signed(channel, payload("group", "b", group=True)))
        assert server.handle_http_request.await_count == 0
        channel.settings.groups["g1"] = GroupBinding(user_id="group", allowed_senders=["external1"])
        await runtime.receive("qq", *signed(channel, payload("group", "c", group=True)))
        await settled(runtime)
        assert server.handle_http_request.await_args.kwargs["user_id"] == "group"
        assert channel.send_text.await_args.args[0] == "g1"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_confirmation_is_not_an_agent_answer_or_implicit_approval(tmp_path):
    response = GatewayProtocol.create_response("r", True, {"status": "needs_confirmation", "tool_name": "dangerous", "tool_call_id": "call1", "response": "not a final answer"})
    runtime, channel, _, server = host(tmp_path, response=response)
    try:
        await runtime.receive("qq", *signed(channel, payload()))
        await settled(runtime)
        row = runtime.store.list_user("alice")[0]
        assert row["execution_status"] == "waiting_confirmation"
        assert channel.send_text.await_args.args[1].startswith("[Runtime]")
        assert "not a final answer" not in channel.send_text.await_args.args[1]
        server.handle_http_request.return_value = GatewayProtocol.create_response("r2", True, {"response": "Approved result"})
        await runtime.receive("qq", *signed(channel, payload("/approve call1", "m2")))
        await settled(runtime)
        args = server.handle_http_request.await_args.kwargs
        assert args["method"] == RequestType.CHAT_CONFIRM and args["params"]["tool_call_id"] == "call1"
        assert args["user_id"] == "alice"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [(ProviderRejected("HTTP_429"), "delivery_failed"), (TimeoutError("a secret URL"), "uncertain")])
async def test_send_failure_does_not_rerun_model_or_blindly_retry(tmp_path, error, expected):
    runtime, channel, _, server = host(tmp_path)
    channel.send_text.side_effect = error
    try:
        value = payload()
        await runtime.receive("qq", *signed(channel, value))
        await settled(runtime)
        row = runtime.store.list_user("alice")[0]
        assert row["state"] == expected
        assert "secret" not in str(row)
        await runtime.receive("qq", *signed(channel, value))
        assert server.handle_http_request.await_count == 1 and channel.send_text.await_count == 1
    finally:
        await runtime.stop()


def test_restart_recovers_queued_work_but_fences_uncertain_effects(tmp_path):
    store = DeliveryStore(tmp_path / "delivery.sqlite3")
    store.enqueue("job1", "qq", "alice", "s", {})
    assert store.claim()["state"] == "processing"
    store.enqueue("job2", "qq", "alice", "s", {})
    restored = DeliveryStore(store.path)
    restored.recover()
    assert restored.get("job1")["state"] == "uncertain"
    assert restored.claim()["delivery_id"] == "job2"
    restored.purge("alice")
    assert restored.list_user("alice") == []


def test_single_instance_lock_is_enforced_and_released(tmp_path):
    first, second = RuntimeLock(tmp_path / "worker.lock"), RuntimeLock(tmp_path / "worker.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another"):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()


@pytest.mark.asyncio
async def test_actual_gateway_conversation_action_chain_commits_owned_channel_history(tmp_path):
    from gateway.server import GatewayServer
    from tests.test_agent_messages import inbox_host
    from tests.test_ambient_service import Core

    core = Core({"action": "answer", "content": "真实 Agent 回复"})
    _, tasks_runtime, conversation, _, manager = inbox_host(tmp_path / "core", core)
    runtime, channel, _, _ = host(tmp_path)
    server = GatewayServer()
    server.message_manager = manager
    server.conversation_service = conversation
    server.capability_service = conversation.capability_service
    server.channels = {"qq": channel}
    runtime.server = server
    try:
        await runtime.receive("qq", *signed(channel, payload("你好")))
        await settled(runtime)
        row = runtime.store.list_user("alice")[0]
        assert row["state"] == "delivered", row
        assert server.channel_adapter_registry.get("qq").metadata.channel_id == "qq"
        messages = manager.get_messages(row["session_id"], user_id="alice")
        assert [item["content"] for item in messages] == ["你好", "真实 Agent 回复"]
        assert len(core.requests) == 1
        assert manager.get_session(row["session_id"], user_id="bob") is None
    finally:
        await runtime.stop()
        await tasks_runtime.shutdown()


@pytest.mark.asyncio
async def test_actual_sensitive_tool_needs_exact_bound_sender_confirmation(tmp_path):
    from gateway.server import GatewayServer
    from tests.test_agent_messages import inbox_host
    from tests.test_ambient_service import Core, call

    core = Core(call("risky.run"), {"action": "answer", "content": "Operation completed."})
    _, task_runtime, conversation, _, manager = inbox_host(tmp_path / "core", core)
    invoke = AsyncMock(return_value={"ok": True})
    conversation.capability_service.register_tool(SimpleNamespace(tool_id="risky.run", name="risky.run", description="Write an external resource", side_effect_level="external_write", input_schema={"type": "object", "properties": {}, "additionalProperties": False}, invoke=invoke))
    runtime, channel, _, _ = host(tmp_path)
    server = GatewayServer()
    server.message_manager, server.conversation_service = manager, conversation
    server.capability_service = conversation.capability_service
    server.channels = {"qq": channel}
    runtime.server = server
    try:
        await runtime.receive("qq", *signed(channel, payload("Perform the operation")))
        await settled(runtime)
        invoke.assert_not_awaited()
        row = runtime.store.list_user("alice")[0]
        pending = manager.get_pending_confirmation(row["session_id"], user_id="alice")
        assert pending and pending["tool_name"] == "risky.run"
        command = f"/approve {pending['tool_call_id']}"
        await runtime.receive("qq", *signed(channel, payload(command, "attacker", sender="external2")))
        invoke.assert_not_awaited()
        await runtime.receive("qq", *signed(channel, payload(command, "approved")))
        await settled(runtime)
        invoke.assert_awaited_once()
        assert manager.get_pending_confirmation(row["session_id"], user_id="alice") is None
        assert channel.send_text.await_args.args[1] == "Operation completed."
        await runtime.receive("qq", *signed(channel, payload(command, "approved")))
        invoke.assert_awaited_once()
    finally:
        await runtime.stop()
        await task_runtime.shutdown()
