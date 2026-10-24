"""DingTalk enterprise robot HTTP callbacks and authenticated robot OpenAPI."""
import asyncio
import base64
import hashlib
import hmac
import json
import time

from .base import ChannelType
from .webhook_channel import ProviderRejected, WebhookChannel
from .webhook_security import fresh_timestamp


class DingTalkChannel(WebhookChannel):
    api_base = "https://api.dingtalk.com/v1.0"

    def __init__(self, settings):
        super().__init__("dingtalk", ChannelType.DINGTALK, settings)
        self.account_id = f"{settings.corp_id}:{settings.robot_code}"
        self._token, self._expires = "", 0
        self._token_lock = asyncio.Lock()

    def accept_webhook(self, headers, body):
        timestamp = headers.get("timestamp", "")
        fresh_timestamp(timestamp, scale=1000)
        secret = self.settings.app_secret.get_secret_value()
        expected = base64.b64encode(hmac.new(secret.encode(), (timestamp + "\n" + secret).encode(), hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(expected, headers.get("sign", "")):
            raise PermissionError("Invalid DingTalk signature")
        data = json.loads(body)
        if data.get("robotCode") != self.settings.robot_code or data.get("senderCorpId") != self.settings.corp_id:
            raise PermissionError("Wrong DingTalk robot or enterprise")
        if data.get("msgtype") != "text" or data.get("conversationType") not in {"1", "2"}:
            return {}, None
        fresh_timestamp(data.get("createAt"), scale=1000, max_age=86400)
        text = (data.get("text") or {}).get("content", "").strip()
        if not text:
            return {}, None
        private = data["conversationType"] == "1"
        if not private and data.get("isInAtList") is not True:
            return {}, None
        sender = data["senderStaffId"]
        if not isinstance(sender, str) or not sender.strip():
            raise ValueError("DingTalk senderStaffId is required")
        return {}, {"message_id": data["msgId"], "sender_id": sender,
                    "receiver_id": sender if private else data["conversationId"],
                    "scope": "private" if private else "group", "content": text, "reply_to": data["msgId"]}

    async def access_token(self):
        async with self._token_lock:
            if time.time() >= self._expires:
                result = await self.json_request("POST", self.api_base + "/oauth2/accessToken", json={"appKey": self.settings.app_key, "appSecret": self.settings.app_secret.get_secret_value()})
                if result.get("code"):
                    raise ProviderRejected(result["code"])
                token, expire = result.get("accessToken"), result.get("expireIn")
                if not isinstance(token, str) or not token or not isinstance(expire, int) or expire <= 60:
                    raise RuntimeError("DingTalk did not confirm an access token")
                self._token, self._expires = token, time.time() + expire - 60
            return self._token

    async def send_text(self, receiver_id, content, *, scope="private", **kwargs):
        token = await self.access_token()
        payload = {"robotCode": self.settings.robot_code, "msgKey": "sampleText", "msgParam": json.dumps({"content": content}, ensure_ascii=False)}
        if scope == "group":
            path = "/robot/groupMessages/send"
            payload["openConversationId"] = receiver_id
        else:
            path = "/robot/oToMessages/batchSend"
            payload["userIds"] = [receiver_id]
        result = await self.json_request("POST", self.api_base + path, headers={"x-acs-dingtalk-access-token": token}, json=payload)
        if result.get("code"):
            raise ProviderRejected(result["code"])
        if any(result.get(key) for key in ("invalidStaffIdList", "flowControlledStaffIdList", "filteredStaffIdList")):
            raise ProviderRejected("RECIPIENT_REJECTED")
        message_id = result.get("processQueryKey")
        if not message_id:
            raise RuntimeError("DingTalk did not confirm delivery")
        return {"success": True, "message_id": str(message_id)}
