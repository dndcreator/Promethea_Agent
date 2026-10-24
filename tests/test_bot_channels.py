import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from channels.qq_channel import QQChannel
from channels.telegram_channel import TelegramChannel
from channels.settings import QQSettings, TelegramSettings, load_settings
from channels.webhook_channel import ProviderRejected


def qq():
    channel = QQChannel(QQSettings(enabled=True, app_id="app1", client_secret="client-private", bot_secret="callback-private"))
    channel.is_running = channel.is_connected = True
    return channel


def payload(text="Hello", identity="m1", *, group=False, sender="external1"):
    return {"op": 0, "id": "event-" + identity, "t": "GROUP_AT_MESSAGE_CREATE" if group else "C2C_MESSAGE_CREATE", "d": {"id": identity, "timestamp": datetime.now(timezone.utc).isoformat(), "author": {"member_openid" if group else "user_openid": sender}, "content": text, **({"group_openid": "g1"} if group else {})}}


def signed(channel, value):
    body = json.dumps(value, ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    return {"x-bot-appid": channel.account_id, "x-signature-timestamp": timestamp, "x-signature-ed25519": channel._key().sign(timestamp.encode() + body).hex()}, body


def test_qq_official_challenge_and_signed_event_integrity():
    channel = qq()
    timestamp = str(int(time.time()))
    ack, event = channel.accept_webhook({"x-bot-appid": "app1"}, json.dumps({"op": 13, "d": {"event_ts": timestamp, "plain_token": "challenge-123"}}).encode())
    channel._key().public_key().verify(bytes.fromhex(ack["signature"]), (timestamp + "challenge-123").encode())
    assert event is None
    assert channel.accept_webhook({"x-bot-appid": "app1"}, json.dumps({"op": 13, "d": {"event_ts": timestamp, "plain_token": "token+/="}}).encode())[0]["plain_token"] == "token+/="
    headers, body = signed(channel, payload())
    ack, event = channel.accept_webhook(headers, body)
    assert ack == {"op": 12, "d": 0}
    assert event["sender_id"] == event["receiver_id"] == "external1"
    assert event["reply_to"] == "m1" and event["scope"] == "private"
    with pytest.raises(PermissionError):
        channel.accept_webhook(headers, body.replace(b"Hello", b"Owned"))
    with pytest.raises(PermissionError):
        channel.accept_webhook({**headers, "x-bot-appid": "other"}, body)
    with pytest.raises(PermissionError):
        channel.accept_webhook({**headers, "x-signature-timestamp": "1"}, body)
    with pytest.raises(PermissionError):
        channel.accept_webhook({**headers, "x-signature-ed25519": "invalid"}, body)
    with pytest.raises(ValueError, match="opaque"):
        channel.accept_webhook({"x-bot-appid": "app1"}, json.dumps({"op": 13, "d": {"event_ts": timestamp, "plain_token": json.dumps(payload())}}).encode())


def test_qq_group_protocol_mention_and_old_or_unsupported_events():
    channel = qq()
    value = payload("<@!bot123> What is next?", group=True)
    event = channel.accept_webhook(*signed(channel, value))[1]
    assert event["scope"] == "group" and event["receiver_id"] == "g1"
    assert event["content"] == "What is next?"
    value["d"]["timestamp"] = "2020-01-01T00:00:00+00:00"
    assert channel.accept_webhook(*signed(channel, value))[1] is None
    assert channel.accept_webhook(*signed(channel, {"op": 0, "t": "FRIEND_ADD", "d": {}}))[1] is None


@pytest.mark.asyncio
async def test_qq_token_cache_provider_errors_and_reply_idempotency_fields():
    channel = qq()
    channel.json_request = AsyncMock(side_effect=[{"access_token": "token-secret", "expires_in": 7200}, {"id": "sent1"}, {"id": "sent2"}])
    await channel.send_text("user/unsafe", "你好", reply_to="m1", sequence=1)
    await channel.send_text("g1", "Group", scope="group", reply_to="m2", sequence=2)
    calls = channel.json_request.await_args_list
    assert len(calls) == 3
    assert calls[0].args[1] == "https://api.bot.qq.com/app/getAppAccessToken"
    assert calls[0].kwargs["json"]["clientSecret"] == "client-private"
    assert calls[1].args[1].endswith("/v2/users/user%2Funsafe/messages")
    assert calls[1].kwargs["json"] == {"msg_type": 0, "content": "你好", "msg_id": "m1", "msg_seq": 1}
    assert calls[2].args[1].endswith("/v2/groups/g1/messages")
    channel.json_request = AsyncMock(return_value={"err_code": 40034005, "message": "private detail"})
    with pytest.raises(ProviderRejected, match="40034005") as error:
        await channel.send_text("g1", "no", reply_to="m1")
    assert "private detail" not in str(error.value)
    channel._expires = 0
    channel.json_request = AsyncMock(return_value={"code": 100016, "message": "secret"})
    with pytest.raises(ProviderRejected, match="100016"):
        await channel.access_token()
    channel._expires = float('inf')
    channel.json_request = AsyncMock(return_value={"timestamp": "accepted but id missing"})
    with pytest.raises(RuntimeError, match="did not confirm"):
        await channel.send_text("external1", "unknown", reply_to="m3")


def test_telegram_authentication_private_text_and_update_dedup_key():
    channel = TelegramChannel(TelegramSettings(enabled=True, bot_token="123:private", webhook_secret="hook-private"))
    value = {"update_id": 71, "message": {"message_id": 5, "date": int(time.time()), "from": {"id": 20}, "chat": {"id": 20, "type": "private"}, "text": "Hi"}}
    headers = {"x-telegram-bot-api-secret-token": "hook-private"}
    ack, event = channel.accept_webhook(headers, json.dumps(value).encode())
    assert ack == {"ok": True} and event["message_id"] == "71" and event["reply_to"] == "5"
    with pytest.raises(PermissionError):
        channel.accept_webhook({}, json.dumps(value).encode())
    value["message"]["chat"]["type"] = "group"
    assert channel.accept_webhook(headers, json.dumps(value).encode())[1] is None


@pytest.mark.asyncio
async def test_telegram_send_preserves_private_destination_and_does_not_enable_parse_mode():
    channel = TelegramChannel(TelegramSettings(enabled=True, bot_token="123:private", webhook_secret="hook-private"))
    channel.json_request = AsyncMock(return_value={"ok": True, "result": {"message_id": 8}})
    assert (await channel.send_text("20", "<b>plain</b>", reply_to="5"))["message_id"] == "8"
    assert channel.json_request.await_args.kwargs["json"] == {"chat_id": "20", "text": "<b>plain</b>", "reply_parameters": {"message_id": 5}}
    channel.json_request.return_value = {"ok": True, "result": {}}
    with pytest.raises(RuntimeError, match="did not confirm"):
        await channel.send_text("20", "unknown", reply_to="5")


def test_operator_channel_env_is_typed_precedes_json_and_hides_secrets(monkeypatch):
    monkeypatch.setenv("CHANNELS__QQ__ENABLED", "true")
    monkeypatch.setenv("CHANNELS__QQ__APP_ID", "env-app")
    monkeypatch.setenv("CHANNELS__QQ__CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("CHANNELS__QQ__BOT_SECRET", "env-hook")
    settings = load_settings({"qq": {"app_id": "file-app", "enabled": False}})
    assert settings.qq.enabled and settings.qq.app_id == "env-app"
    assert "env-secret" not in repr(settings)


def test_qq_discovery_uses_existing_extension_loader_and_excludes_secret_config(tmp_path, monkeypatch):
    from pathlib import Path
    from gateway_integration import GatewayIntegration
    from core.plugins.loader import PluginLoadOptions, load_promethea_plugins
    from core.plugins import runtime

    monkeypatch.setattr(runtime, "_active_registry", runtime._active_registry)
    monkeypatch.setattr(runtime, "_active_key", runtime._active_key)

    monkeypatch.setenv("CHANNELS__QQ__ENABLED", "true")
    monkeypatch.setenv("CHANNELS__QQ__APP_ID", "fixture-app")
    monkeypatch.setenv("CHANNELS__QQ__CLIENT_SECRET", "fixture-client-private")
    monkeypatch.setenv("CHANNELS__QQ__BOT_SECRET", "fixture-callback-private")
    integration = GatewayIntegration(str(tmp_path / "missing.json"))
    integration.config["channels"]["queue_limit"] = 5
    config = integration._build_plugins_config()
    assert config["plugins"]["qq"]["enabled"]
    assert "fixture-client-private" not in json.dumps(config)
    assert "fixture-callback-private" not in json.dumps(config)
    registry = load_promethea_plugins(PluginLoadOptions(workspace_dir=str(Path(__file__).resolve().parents[1]), extensions_dir="extensions", config=config, cache=False, mode="full", allow={"qq"}))
    channel = next(entry.channel for entry in registry.channels if entry.channel_id == "qq")
    assert isinstance(channel, QQChannel) and channel.account_id == "fixture-app"
