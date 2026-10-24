"""Feishu application bot: encrypted event subscriptions and OpenAPI replies."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote

from .base import ChannelType
from .webhook_channel import ProviderRejected, WebhookChannel
from .webhook_security import decrypt_cbc, fresh_timestamp


class FeishuChannel(WebhookChannel):
    api_base = "https://open.feishu.cn/open-apis"

    def __init__(self, settings):
        super().__init__("feishu", ChannelType.FEISHU, settings)
        self.account_id = settings.app_id
        self._token, self._expires = "", 0
        self._token_lock = asyncio.Lock()

    def accept_webhook(self, headers, body):
        outer = json.loads(body)
        if not isinstance(outer, dict) or not isinstance(outer.get("encrypt"), str):
            raise PermissionError("Encrypted Feishu callbacks are required")
        encrypted = base64.b64decode(outer["encrypt"], validate=True)
        key = hashlib.sha256(self.settings.encrypt_key.get_secret_value().encode()).digest()
        data = json.loads(decrypt_cbc(encrypted[16:], key, encrypted[:16]))
        header = data.get("header") or {}
        token = data.get("token") if data.get("type") == "url_verification" else header.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.settings.verification_token.get_secret_value()):
            raise PermissionError("Wrong Feishu verification token")
        # URL verification lacks signature headers; encrypted challenge and token
        # authenticate it, and it can never dispatch a user message.
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            if not isinstance(challenge, str) or not 1 <= len(challenge) <= 1024:
                raise ValueError("Invalid Feishu challenge")
            return {"challenge": challenge}, None
        timestamp = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")
        fresh_timestamp(timestamp)
        expected = hashlib.sha256((timestamp + nonce + self.settings.encrypt_key.get_secret_value()).encode() + body).hexdigest()
        if not nonce or not hmac.compare_digest(expected, headers.get("x-lark-signature", "")):
            raise PermissionError("Invalid Feishu signature")
        if header.get("app_id") != self.account_id:
            raise PermissionError("Wrong Feishu application")
        if header.get("event_type") != "im.message.receive_v1":
            return {}, None
        event = data.get("event") or {}
        sender, message = event.get("sender") or {}, event.get("message") or {}
        if sender.get("sender_type") != "user" or message.get("message_type") != "text":
            return {}, None
        fresh_timestamp(message.get("create_time"), scale=1000, max_age=86400)
        kind = message.get("chat_type")
        if kind not in {"p2p", "group"}:
            return {}, None
        text = json.loads(message.get("content") or "{}").get("text", "")
        for mention in message.get("mentions") or []:
            key = mention.get("key")
            if isinstance(key, str) and key:
                text = text.replace(key, "@" + str(mention.get("name") or "user"))
        if not text.strip():
            return {}, None
        return {}, {"message_id": message["message_id"], "sender_id": sender["sender_id"]["open_id"],
                    "receiver_id": message["chat_id"], "scope": "private" if kind == "p2p" else "group",
                    "content": text.strip(), "reply_to": message["message_id"]}

    async def access_token(self):
        async with self._token_lock:
            if time.time() >= self._expires:
                result = await self.json_request("POST", self.api_base + "/auth/v3/tenant_access_token/internal", json={"app_id": self.account_id, "app_secret": self.settings.app_secret.get_secret_value()})
                if result.get("code") != 0:
                    raise ProviderRejected(result.get("code", "INVALID_TOKEN_RESPONSE"))
                token, expire = result.get("tenant_access_token"), result.get("expire")
                if not isinstance(token, str) or not token or not isinstance(expire, int) or expire <= 60:
                    raise RuntimeError("Feishu did not confirm an access token")
                self._token, self._expires = token, time.time() + expire - 60
            return self._token

    async def send_text(self, receiver_id, content, *, reply_to, sequence=1, **kwargs):
        token = await self.access_token()
        # Reply to the original message, preserving chat/thread. UUID remains
        # stable across an explicit retry of the same persisted segment.
        identity = hashlib.sha256(f"{self.account_id}:{reply_to}:{sequence}".encode()).hexdigest()[:50]
        result = await self.json_request("POST", self.api_base + f"/im/v1/messages/{quote(reply_to, safe='')}/reply", headers={"Authorization": f"Bearer {token}"}, json={"msg_type": "text", "content": json.dumps({"text": content}, ensure_ascii=False), "uuid": identity})
        if "code" not in result:
            raise RuntimeError("Feishu did not confirm delivery")
        if result["code"] != 0:
            raise ProviderRejected(result["code"])
        message_id = (result.get("data") or {}).get("message_id")
        if not message_id:
            raise RuntimeError("Feishu did not confirm delivery")
        return {"success": True, "message_id": str(message_id)}
