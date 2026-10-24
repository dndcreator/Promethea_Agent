"""QQ official bot Webhook and OpenAPI v2. No personal-account bridge."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .base import ChannelType
from .settings import QQSettings
from .webhook_channel import WebhookChannel, ProviderRejected


class QQChannel(WebhookChannel):
    reply_window_s = 300

    def __init__(self, settings: QQSettings):
        super().__init__("qq", ChannelType.QQ, settings)
        self.account_id = settings.app_id
        self._token, self._expires = "", 0
        self._token_lock = asyncio.Lock()

    def _key(self):
        secret = self.settings.bot_secret.get_secret_value().encode()
        if not secret:
            raise ValueError("missing bot signing secret")
        return Ed25519PrivateKey.from_private_bytes((secret * (32 // len(secret) + 1))[:32])

    def accept_webhook(self, headers, body):
        if headers.get("x-bot-appid") != self.account_id:
            raise PermissionError("wrong bot app id")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("invalid QQ payload")
        if payload.get("op") == 13:
            data = payload.get("d") or {}
            token, timestamp = data.get("plain_token", ""), data.get("event_ts", "")
            # An unsigned challenge must not become a signing oracle for JSON events.
            if not isinstance(token, str) or not 1 <= len(token) <= 256:
                raise ValueError("invalid opaque challenge")
            try:
                structured = json.loads(token)
            except ValueError:
                structured = None
            if isinstance(structured, dict):
                raise ValueError("invalid opaque challenge")
            self._fresh(timestamp)
            return {"plain_token": token, "signature": self._key().sign((timestamp + token).encode()).hex()}, None
        timestamp = headers.get("x-signature-timestamp", "")
        self._fresh(timestamp)
        try:
            self._key().public_key().verify(bytes.fromhex(headers.get("x-signature-ed25519", "")), timestamp.encode() + body)
        except (InvalidSignature, ValueError):
            raise PermissionError("invalid QQ signature") from None
        event = self.normalize(payload) if payload.get("op") == 0 else None
        return {"op": 12, "d": 0}, event

    def _fresh(self, timestamp):
        if not isinstance(timestamp, str) or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > self.settings.signature_max_age_s:
            raise PermissionError("expired or invalid QQ timestamp")

    def normalize(self, payload):
        event = payload.get("t")
        if event not in {"C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"}:
            return None
        data = payload.get("d") or {}
        if not isinstance(data, dict):
            raise ValueError("invalid message data")
        timestamp = str(data.get("timestamp") or "")
        try:
            sent_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if sent_at.tzinfo is None or abs(time.time() - sent_at.timestamp()) > 86400:
                return None
        except ValueError:
            return None
        author = data.get("author") or {}
        if author.get("bot"):
            return None
        group = event == "GROUP_AT_MESSAGE_CREATE"
        sender = str(author.get("member_openid" if group else "user_openid") or author.get("id") or "")
        receiver = str(data.get("group_openid") or "") if group else sender
        text = str(data.get("content") or "").strip()
        if group:
            text = re.sub(r"^<@!?[A-Za-z0-9_]+>\s*", "", text)
        if not sender or not receiver or not data.get("id") or not text:
            return None
        return {"message_id": str(data["id"]), "sender_id": sender, "receiver_id": receiver, "scope": "group" if group else "private", "content": text, "reply_to": str(data["id"])}

    async def access_token(self):
        async with self._token_lock:
            if time.monotonic() >= self._expires:
                value = await self.json_request("POST", "https://api.bot.qq.com/app/getAppAccessToken", json={"appId": self.account_id, "clientSecret": self.settings.client_secret.get_secret_value()})
                if value.get("code") or not value.get("access_token"):
                    raise ProviderRejected(value.get("code", "TOKEN_INVALID"))
                self._token = value["access_token"]
                self._expires = time.monotonic() + max(1, int(value.get("expires_in", 0)) - 60)
            return self._token

    async def send_text(self, receiver_id, content, *, scope="private", reply_to, sequence=1, **kwargs):
        token = await self.access_token()
        family = "groups" if scope == "group" else "users"
        data = await self.json_request("POST", f"https://api.bot.qq.com/v2/{family}/{quote(receiver_id, safe='')}/messages", headers={"Authorization": f"QQBot {token}", "X-Union-Appid": self.account_id}, json={"content": content, "msg_type": 0, "msg_id": reply_to, "msg_seq": sequence})
        if data.get("err_code") or data.get("code"):
            raise ProviderRejected(data.get("err_code") or data.get("code"))
        if not data.get("id"):
            raise RuntimeError("provider did not confirm a message id")
        return {"success": True, "message_id": str(data["id"])}
