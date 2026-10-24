import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from gateway.http.routes import channels, auth
from gateway.http.routes.auth import get_current_user_id
from gateway.http.schemas import ChannelBindRequest
from tests.test_channel_delivery import host, settled
from tests.test_bot_channels import signed, payload


@pytest.mark.asyncio
async def test_signed_webhook_and_controls_enforce_separate_authority(tmp_path, monkeypatch):
    runtime, channel, identities, _ = host(tmp_path)
    monkeypatch.setattr(channels, "get_gateway_server", lambda: SimpleNamespace(channel_delivery=runtime))
    monkeypatch.setattr(channels, "user_manager", SimpleNamespace(identity_store=identities))
    app = FastAPI()
    app.include_router(channels.router, prefix="/api")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        assert (await client.get("/api/channels")).status_code == 401
        headers, body = signed(channel, payload())
        assert (await client.post("/api/channels/qq/webhook", headers=headers, content=body)).json() == {"op": 12, "d": 0}
        assert (await client.post("/api/channels/qq/webhook", content=body)).status_code == 403
        assert (await client.post("/api/channels/qq/webhook", headers=headers, content=b"x" * 1_000_001)).status_code == 413
        await settled(runtime)
        app.dependency_overrides[get_current_user_id] = lambda: "alice"
        result = (await client.get("/api/channels")).json()
        assert result[0]["bound"] and "secret" not in str(result)
        deliveries = (await client.get("/api/channels/deliveries")).json()
        assert len(deliveries) == 1 and "envelope" not in deliveries[0]
        assert (await client.post("/api/channels/pairings", json={"channel": "qq"})).json()["command"].startswith("/bind ")
        identity = deliveries[0]["delivery_id"]
        assert (await client.post(f"/api/channels/deliveries/{identity}/retry")).status_code == 409
        app.dependency_overrides[get_current_user_id] = lambda: "bob"
        assert (await client.get("/api/channels/deliveries")).json() == []
        assert (await client.post(f"/api/channels/deliveries/{identity}/retry")).status_code == 404
        app.dependency_overrides[get_current_user_id] = lambda: "alice"
        runtime.server.channels.clear()
        assert (await client.get("/api/channels")).json()[0]["running"] is False
        assert (await client.delete("/api/channels/qq/binding")).status_code == 200
        assert identities.get_channels("alice") == {}
        runtime.server.channels["qq"] = channel
        await runtime.stop()
        assert (await client.get("/api/channels")).json()[0]["running"] is False
        assert (await client.post("/api/channels/pairings", json={"channel": "qq"})).status_code == 503
    finally:
        await client.aclose()
        await runtime.stop()


@pytest.mark.asyncio
async def test_raw_id_claim_is_not_a_verified_pairing():
    with pytest.raises(HTTPException) as caught:
        await auth.bind_channel(ChannelBindRequest(channel="qq:app1", account_id="victim"), user_id="attacker")
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_queue_backpressure_and_revocation_precede_model_execution(tmp_path):
    runtime, channel, identities, server = host(tmp_path, queue_limit=1)
    try:
        await runtime.receive("qq", *signed(channel, payload()))
        # No scheduling point has occurred: the first event is durably queued.
        with pytest.raises(OverflowError):
            await runtime.receive("qq", *signed(channel, payload(identity="m2")))
        identities.unbind_channel("alice", "qq:app1")
        await settled(runtime)
        assert runtime.store.list_user("alice")[0]["state"] == "revoked"
        server.handle_http_request.assert_not_awaited()
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_shutdown_does_not_replay_a_started_agent_turn(tmp_path):
    runtime, channel, identities, server = host(tmp_path)
    entered = asyncio.Event()
    async def running(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    server.handle_http_request.side_effect = running
    await runtime.receive("qq", *signed(channel, payload()))
    await entered.wait()
    await runtime.stop()
    row = runtime.store.list_user("alice")[0]
    assert row["state"] == "uncertain"
    from channels.delivery_runtime import ChannelDeliveryRuntime
    restored = ChannelDeliveryRuntime(server=server, identities=identities, settings=runtime.settings, path=runtime.store.path)
    restored.start()
    try:
        await asyncio.sleep(0.02)
        assert server.handle_http_request.await_count == 1
    finally:
        await restored.stop()


@pytest.mark.asyncio
async def test_legacy_channel_event_cannot_bypass_verified_ingress(tmp_path):
    from gateway.events import EventEmitter
    from gateway.protocol import EventType
    from gateway.conversation_service import ConversationService
    from unittest.mock import AsyncMock

    events = EventEmitter()
    service = ConversationService(event_emitter=events)
    service._enqueue_message = AsyncMock()
    await events.emit(EventType.CHANNEL_MESSAGE, {"channel": "qq", "sender": "victim", "content": "run something"})
    service._enqueue_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_webhook_plugin_can_pair_and_use_gateway_without_provider_name_branches(tmp_path, monkeypatch):
    from channels.base import ChannelType
    from channels.settings import BotSettings
    from channels.webhook_channel import WebhookChannel
    from channels.adapter_registry import build_default_adapter_registry
    from unittest.mock import AsyncMock

    runtime, _, identities, server = host(tmp_path)
    custom = WebhookChannel("community", ChannelType.WEBHOOK, BotSettings(enabled=True))
    custom.account_id = "custom-bot"
    custom.is_running = custom.is_connected = True
    custom.accept_webhook = lambda headers, body: ({"accepted": True}, {"message_id": "custom1", "sender_id": "custom-user", "receiver_id": "custom-user", "scope": "private", "content": body.decode(), "reply_to": "custom1"})
    custom.send_text = AsyncMock(return_value={"success": True, "message_id": "sent"})
    server.channels["community"] = custom
    server.channel_adapter_registry = build_default_adapter_registry()
    monkeypatch.setattr(channels, "get_gateway_server", lambda: SimpleNamespace(channel_delivery=runtime))
    monkeypatch.setattr(channels, "user_manager", SimpleNamespace(identity_store=identities))
    from gateway.public_contracts import ChannelPairingRequest
    try:
        proof = await channels.pairing(ChannelPairingRequest(channel="community"), user_id="bob")
        await runtime.receive("community", {}, proof["command"].encode())
        await settled(runtime)
        assert identities.get_by_channel("community:custom-bot", "custom-user")["user_id"] == "bob"
        assert server.channel_adapter_registry.get("community").metadata.channel_id == "community"
        assert custom.send_text.await_args.args[0] == "custom-user"
        assert (await channels.unbind("community", user_id="bob"))["ok"]
        assert identities.get_by_channel("community:custom-bot", "custom-user") is None
    finally:
        await runtime.stop()
