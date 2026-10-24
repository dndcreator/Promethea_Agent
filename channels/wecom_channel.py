"""WeCom self-built application: encrypted callbacks and application messages."""
import asyncio
import base64
import hashlib
import hmac
import struct
import time

from .base import ChannelType
from .webhook_channel import ProviderRejected, WebhookChannel
from .webhook_security import decrypt_cbc, fresh_timestamp, xml_fields


class WeComChannel(WebhookChannel):
    api_base = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, settings):
        super().__init__("wecom", ChannelType.WECOM, settings)
        self.account_id = f"{settings.corp_id}:{settings.agent_id}"
        self._token, self._expires = "", 0
        self._token_lock = asyncio.Lock()

    def _decrypt(self, encrypted, query):
        timestamp, nonce = query.get("timestamp", ""), query.get("nonce", "")
        fresh_timestamp(timestamp)
        if not nonce or len(nonce) > 256:
            raise PermissionError("Invalid WeCom nonce")
        expected = hashlib.sha1("".join(sorted((self.settings.callback_token.get_secret_value(), timestamp, nonce, encrypted))).encode()).hexdigest()
        if not hmac.compare_digest(expected, query.get("msg_signature", "")):
            raise PermissionError("Invalid WeCom signature")
        key = base64.b64decode(self.settings.encoding_aes_key.get_secret_value() + "=", validate=True)
        plain = decrypt_cbc(base64.b64decode(encrypted, validate=True), key, key[:16], padding_bits=256)
        if len(plain) < 20:
            raise PermissionError("Invalid WeCom envelope")
        size = struct.unpack("!I", plain[16:20])[0]
        if size > len(plain) - 20 or plain[20 + size:] != self.settings.corp_id.encode():
            raise PermissionError("Wrong WeCom enterprise")
        return plain[20:20 + size]

    def verify_webhook(self, query):
        encrypted = query.get("echostr", "")
        if not isinstance(encrypted, str) or not 1 <= len(encrypted) <= 4096:
            raise ValueError("Invalid WeCom challenge")
        return self._decrypt(encrypted, query).decode("utf-8")

    def accept_request(self, headers, body, query):
        outer = xml_fields(body)
        data = xml_fields(self._decrypt(outer["Encrypt"], query))
        if data.get("ToUserName") != self.settings.corp_id or data.get("AgentID") != str(self.settings.agent_id):
            raise PermissionError("Wrong WeCom application")
        if data.get("MsgType") != "text":
            return "success", None
        fresh_timestamp(data.get("CreateTime"), max_age=86400)
        text = data.get("Content", "").strip()
        if not text:
            return "success", None
        sender = data["FromUserName"]
        return "success", {"message_id": data["MsgId"], "sender_id": sender, "receiver_id": sender,
                           "scope": "private", "content": text, "reply_to": data["MsgId"]}

    async def access_token(self):
        async with self._token_lock:
            if time.time() >= self._expires:
                result = await self.json_request("GET", self.api_base + "/gettoken", params={"corpid": self.settings.corp_id, "corpsecret": self.settings.app_secret.get_secret_value()})
                if result.get("errcode", 0) != 0:
                    raise ProviderRejected(result["errcode"])
                token, expire = result.get("access_token"), result.get("expires_in")
                if not isinstance(token, str) or not token or not isinstance(expire, int) or expire <= 60:
                    raise RuntimeError("WeCom did not confirm an access token")
                self._token, self._expires = token, time.time() + expire - 60
            return self._token

    async def send_text(self, receiver_id, content, *, scope="private", **kwargs):
        if scope != "private" or receiver_id == "@all" or "|" in receiver_id:
            raise ProviderRejected("INVALID_PRIVATE_RECIPIENT")
        token = await self.access_token()
        result = await self.json_request("POST", self.api_base + "/message/send", params={"access_token": token}, json={"touser": receiver_id, "agentid": self.settings.agent_id, "msgtype": "text", "text": {"content": content}})
        if "errcode" not in result:
            raise RuntimeError("WeCom did not confirm delivery")
        if result["errcode"] != 0:
            raise ProviderRejected(result["errcode"])
        if result.get("invaliduser") or result.get("unlicenseduser"):
            raise ProviderRejected("RECIPIENT_REJECTED")
        if not result.get("msgid"):
            raise RuntimeError("WeCom did not confirm delivery")
        return {"success": True, "message_id": str(result["msgid"])}
