import base64
import hashlib
import hmac
import json
import struct
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.sax.saxutils import escape

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from fastapi import FastAPI

from channels.dingtalk_channel import DingTalkChannel
from channels.feishu_channel import FeishuChannel
from channels.wecom_channel import WeComChannel
from channels.settings import DingTalkSettings, FeishuSettings, WeComSettings, load_settings
from channels.webhook_channel import ProviderRejected
from gateway.http.routes import channels as routes
from tests.test_channel_delivery import host, settled


def channel_for(name):
    if name == "feishu":
        return FeishuChannel(FeishuSettings(enabled=True, app_id="app1", app_secret="app-private", verification_token="verify-private", encrypt_key="encrypt-private"))
    if name == "dingtalk":
        return DingTalkChannel(DingTalkSettings(enabled=True, app_key="app1", app_secret="app-private", robot_code="bot1", corp_id="corp1"))
    return WeComChannel(WeComSettings(enabled=True, corp_id="corp1", agent_id=7, app_secret="app-private", callback_token="verify-private", encoding_aes_key=base64.b64encode(bytes(range(32))).decode().rstrip("=")))


def encrypt(plain, key, iv, block=128):
    padder = PKCS7(block).padder()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return cipher.update(padder.update(plain) + padder.finalize()) + cipher.finalize()


def feishu_request(channel, text="你好", message_id="m1", *, group=False, app_id="app1", challenge=False):
    if challenge:
        data = {"type": "url_verification", "token": "verify-private", "challenge": "challenge-text"}
    else:
        data = {"schema": "2.0", "header": {"app_id": app_id, "token": "verify-private", "event_type": "im.message.receive_v1"}, "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "external1"}},
            "message": {"message_id": message_id, "create_time": str(int(time.time() * 1000)), "message_type": "text", "content": json.dumps({"text": text}), "chat_id": "g1" if group else "chat1", "chat_type": "group" if group else "p2p"}}}
    key = hashlib.sha256(channel.settings.encrypt_key.get_secret_value().encode()).digest()
    iv = bytes(range(16))
    body = json.dumps({"encrypt": base64.b64encode(iv + encrypt(json.dumps(data).encode(), key, iv)).decode()}).encode()
    timestamp, nonce = str(int(time.time())), "nonce-1"
    signature = hashlib.sha256((timestamp + nonce + channel.settings.encrypt_key.get_secret_value()).encode() + body).hexdigest()
    return {"x-lark-request-timestamp": timestamp, "x-lark-request-nonce": nonce, "x-lark-signature": signature}, body, {}


def dingtalk_request(channel, text="你好", message_id="m1", *, group=False, **updates):
    data = {"robotCode": "bot1", "senderCorpId": "corp1", "senderStaffId": "external1", "conversationId": "g1", "conversationType": "2" if group else "1", "msgId": message_id, "createAt": int(time.time() * 1000), "msgtype": "text", "isInAtList": group, "text": {"content": text}, **updates}
    timestamp = str(int(time.time() * 1000))
    secret = channel.settings.app_secret.get_secret_value()
    signature = base64.b64encode(hmac.new(secret.encode(), (timestamp + "\n" + secret).encode(), hashlib.sha256).digest()).decode()
    return {"timestamp": timestamp, "sign": signature}, json.dumps(data).encode(), {}


def wecom_envelope(channel, plain, *, corp="corp1"):
    key = base64.b64decode(channel.settings.encoding_aes_key.get_secret_value() + "=")
    envelope = bytes(range(16)) + struct.pack("!I", len(plain)) + plain + corp.encode()
    encrypted = base64.b64encode(encrypt(envelope, key, key[:16], 256)).decode()
    timestamp, nonce = str(int(time.time())), "nonce-1"
    signature = hashlib.sha1("".join(sorted(("verify-private", timestamp, nonce, encrypted))).encode()).hexdigest()
    return encrypted, {"timestamp": timestamp, "nonce": nonce, "msg_signature": signature}


def wecom_request(channel, text="你好", message_id="m1", **updates):
    data = {"ToUserName": "corp1", "FromUserName": "external1", "AgentID": "7", "CreateTime": str(int(time.time())), "MsgType": "text", "Content": text, "MsgId": message_id, **updates}
    plain = ("<xml>" + "".join(f"<{key}>{escape(value)}</{key}>" for key, value in data.items()) + "</xml>").encode()
    encrypted, query = wecom_envelope(channel, plain)
    return {}, f"<xml><Encrypt>{encrypted}</Encrypt></xml>".encode(), query


REQUESTS = {"feishu": feishu_request, "dingtalk": dingtalk_request, "wecom": wecom_request}


@pytest.mark.parametrize("name", REQUESTS)
def test_enterprise_authentication_and_normalized_private_text(name):
    channel = channel_for(name)
    headers, body, query = REQUESTS[name](channel)
    ack, event = channel.accept_request(headers, body, query)
    assert ack == ("success" if name == "wecom" else {})
    assert event["content"] == "你好" and event["scope"] == "private"
    assert event["sender_id"] == "external1" and event["message_id"] == event["reply_to"] == "m1"
    if name == "wecom":
        query["msg_signature"] = "bad"
    else:
        headers["sign" if name == "dingtalk" else "x-lark-signature"] = "bad"
    with pytest.raises(PermissionError):
        channel.accept_request(headers, body, query)


def test_feishu_encrypted_challenge_app_fence_and_raw_body_signature():
    channel = channel_for("feishu")
    _, body, _ = feishu_request(channel, challenge=True)
    assert channel.accept_webhook({}, body) == ({"challenge": "challenge-text"}, None)
    with pytest.raises(PermissionError):
        channel.accept_webhook({}, b'{"type":"url_verification","token":"verify-private","challenge":"forged"}')
    headers, body, _ = feishu_request(channel, app_id="other")
    with pytest.raises(PermissionError, match="application"):
        channel.accept_webhook(headers, body)
    headers, body, _ = feishu_request(channel)
    with pytest.raises(PermissionError):
        channel.accept_webhook(headers, body + b" ")
    with pytest.raises(PermissionError, match="timestamp"):
        channel.accept_webhook({**headers, "x-lark-request-timestamp": "1"}, body)


def test_dingtalk_enterprise_staff_group_and_no_session_webhook_use():
    channel = channel_for("dingtalk")
    request = dingtalk_request(channel, group=True, sessionWebhook="http://127.0.0.1/private")
    event = channel.accept_request(*request)[1]
    assert event["receiver_id"] == "g1" and event["scope"] == "group" and "sessionWebhook" not in event
    assert channel.accept_request(*dingtalk_request(channel, group=True, isInAtList=False))[1] is None
    with pytest.raises(PermissionError):
        channel.accept_request(*dingtalk_request(channel, senderCorpId="other"))
    with pytest.raises(ValueError):
        channel.accept_request(*dingtalk_request(channel, senderStaffId=None))


def test_wecom_url_challenge_corp_app_padding_and_xml_validation():
    channel = channel_for("wecom")
    encrypted, query = wecom_envelope(channel, b"exact-challenge")
    assert channel.verify_webhook({**query, "echostr": encrypted}) == "exact-challenge"
    encrypted, query = wecom_envelope(channel, b"wrong", corp="other")
    with pytest.raises(PermissionError, match="enterprise"):
        channel.verify_webhook({**query, "echostr": encrypted})
    with pytest.raises(PermissionError, match="application"):
        channel.accept_request(*wecom_request(channel, AgentID="99"))
    assert channel.accept_request(*wecom_request(channel, MsgType="image"))[1] is None
    from channels.webhook_security import xml_fields
    with pytest.raises(ValueError):
        xml_fields(b'<!DOCTYPE xml [<!ENTITY x "boom">]><xml><Encrypt>&x;</Encrypt></xml>')
    with pytest.raises(ValueError):
        xml_fields(b'<xml><Encrypt>a</Encrypt><Encrypt>b</Encrypt></xml>')
    with pytest.raises(ValueError):
        xml_fields('<xml/>'.encode('utf-16'))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", REQUESTS)
async def test_enterprise_token_cache_correct_send_api_and_uncertain_responses(name):
    channel = channel_for(name)
    token = {"feishu": {"code": 0, "tenant_access_token": "secret-token", "expire": 7200}, "dingtalk": {"accessToken": "secret-token", "expireIn": 7200}, "wecom": {"errcode": 0, "access_token": "secret-token", "expires_in": 7200}}[name]
    result = {"feishu": {"code": 0, "data": {"message_id": "sent1"}}, "dingtalk": {"processQueryKey": "sent1"}, "wecom": {"errcode": 0, "msgid": "sent1"}}[name]
    channel.json_request = AsyncMock(side_effect=[token, result, result])
    assert (await channel.send_text("external1", "回复", reply_to="m/1", sequence=1))["message_id"] == "sent1"
    await channel.send_text("external1", "回复", reply_to="m/1", sequence=1)
    calls = channel.json_request.await_args_list
    assert len(calls) == 3
    send = calls[1]
    if name == "feishu":
        assert send.args[1].endswith("/im/v1/messages/m%2F1/reply")
        assert send.kwargs["json"]["uuid"] == calls[2].kwargs["json"]["uuid"]
        assert json.loads(send.kwargs["json"]["content"]) == {"text": "回复"}
    elif name == "dingtalk":
        assert send.args[1].endswith("/robot/oToMessages/batchSend")
        assert send.kwargs["json"]["userIds"] == ["external1"]
    else:
        assert send.kwargs["json"] == {"touser": "external1", "agentid": 7, "msgtype": "text", "text": {"content": "回复"}}
    channel.json_request = AsyncMock(return_value={})
    with pytest.raises(RuntimeError, match="did not confirm"):
        await channel.send_text("external1", "unknown", reply_to="m1")
    channel.json_request.return_value = {"code" if name != "wecom" else "errcode": 40013}
    with pytest.raises(ProviderRejected, match="40013"):
        await channel.send_text("external1", "refused", reply_to="m1")


@pytest.mark.asyncio
async def test_dingtalk_group_and_recipient_rejection_wecom_no_broadcast():
    channel = channel_for("dingtalk")
    channel._token, channel._expires = "token", float("inf")
    channel.json_request = AsyncMock(return_value={"processQueryKey": "sent"})
    await channel.send_text("g1", "hello", scope="group")
    assert channel.json_request.await_args.args[1].endswith("/robot/groupMessages/send")
    assert channel.json_request.await_args.kwargs["json"]["openConversationId"] == "g1"
    channel.json_request.return_value = {"processQueryKey": "sent", "filteredStaffIdList": ["external1"]}
    with pytest.raises(ProviderRejected):
        await channel.send_text("external1", "filtered")
    wecom = channel_for("wecom")
    for receiver in ("@all", "user1|user2"):
        with pytest.raises(ProviderRejected):
            await wecom.send_text(receiver, "no broadcast")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", REQUESTS)
async def test_enterprise_pairing_existing_delivery_chain_and_duplicate_receipts(name, tmp_path):
    runtime, _, identities, server = host(tmp_path)
    channel = channel_for(name)
    channel.is_running = channel.is_connected = True
    channel.send_text = AsyncMock(return_value={"success": True, "message_id": "s1"})
    server.channels = {name: channel}
    try:
        command = identities.issue_channel_pairing("bob", runtime.namespace(channel))["command"]
        await runtime.receive(name, *REQUESTS[name](channel, command, "bind1"))
        await settled(runtime)
        assert server.handle_http_request.await_count == 0
        assert identities.get_by_channel(runtime.namespace(channel), "external1")["user_id"] == "bob"
        request = REQUESTS[name](channel)
        await runtime.receive(name, *request)
        await settled(runtime)
        await runtime.receive(name, *request)
        assert server.handle_http_request.await_count == 1
        assert server.handle_http_request.await_args.kwargs["user_id"] == "bob"
        assert runtime.store.list_user("bob")[0]["state"] == "delivered"
        identities.unbind_channel("bob", runtime.namespace(channel))
        await runtime.receive(name, *REQUESTS[name](channel, "not authorized", "m2"))
        assert server.handle_http_request.await_count == 1
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_wecom_http_get_and_post_ack_are_exact_plaintext(tmp_path, monkeypatch):
    runtime, _, identities, server = host(tmp_path)
    channel = channel_for("wecom")
    channel.is_running = channel.is_connected = True
    server.channels = {"wecom": channel}
    monkeypatch.setattr(routes, "get_gateway_server", lambda: SimpleNamespace(channel_delivery=runtime))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            encrypted, query = wecom_envelope(channel, b"exact-challenge")
            response = await client.get("/api/channels/wecom/webhook", params={**query, "echostr": encrypted})
            assert response.status_code == 200 and response.content == b"exact-challenge"
            assert response.headers["content-type"].startswith("text/plain")
            assert (await client.get("/api/channels/wecom/webhook", params={**query, "echostr": encrypted, "msg_signature": "bad"})).status_code == 403
            _, body, query = wecom_request(channel)
            response = await client.post("/api/channels/wecom/webhook", params=query, content=body)
            assert response.status_code == 200 and response.content == b"success"
            assert server.handle_http_request.await_count == 0
    finally:
        await runtime.stop()


@pytest.mark.parametrize("name", REQUESTS)
def test_enterprise_settings_require_real_credentials_and_hide_them(name, monkeypatch, tmp_path):
    from pathlib import Path
    from gateway_integration import GatewayIntegration
    from core.plugins.loader import PluginLoadOptions, load_promethea_plugins
    from core.plugins import runtime
    monkeypatch.setattr(runtime, "_active_registry", runtime._active_registry)
    monkeypatch.setattr(runtime, "_active_key", runtime._active_key)
    channel = channel_for(name)
    for key, value in channel.settings:
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if key in {"groups", "request_timeout_s", "reply_chars", "max_reply_parts"}:
            continue
        monkeypatch.setenv(f"CHANNELS__{name.upper()}__{key.upper()}", str(value).lower() if isinstance(value, bool) else str(value))
    settings = load_settings()
    assert getattr(settings, name).enabled
    config = GatewayIntegration(str(tmp_path / "missing.json"))._build_plugins_config()
    encoded = json.dumps(config)
    for secret in ("app-private", "verify-private", "encrypt-private"):
        assert secret not in encoded
    assert config["plugins"][name]["enabled"]
    registry = load_promethea_plugins(PluginLoadOptions(workspace_dir=str(Path(__file__).resolve().parents[1]), extensions_dir="extensions", config=config, cache=False, mode="full", allow={name}))
    registered = next(entry.channel for entry in registry.channels if entry.channel_id == name)
    assert type(registered) is type(channel) and registered.account_id == channel.account_id
