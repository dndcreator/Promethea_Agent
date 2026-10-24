"""Telegram Bot API Webhook transport using a deployment-owned secret header."""
import hmac
import json
import time
from urllib.parse import quote

from .base import ChannelType
from .settings import TelegramSettings
from .webhook_channel import WebhookChannel, ProviderRejected


class TelegramChannel(WebhookChannel):
    def __init__(self, settings: TelegramSettings):
        super().__init__("telegram", ChannelType.TELEGRAM, settings)
        self.account_id = settings.bot_token.get_secret_value().split(":", 1)[0]

    def accept_webhook(self, headers, body):
        if not hmac.compare_digest(headers.get("x-telegram-bot-api-secret-token", ""), self.settings.webhook_secret.get_secret_value()):
            raise PermissionError("invalid Telegram webhook secret")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("invalid Telegram payload")
        message = payload.get("message") or {}
        sender, chat = message.get("from") or {}, message.get("chat") or {}
        if sender.get("is_bot") or not message.get("text") or payload.get("update_id") is None or chat.get("type") != "private":
            return {"ok": True}, None  # No group/edited/channel-post ingestion in this transport.
        if not sender.get("id") or not chat.get("id") or not message.get("message_id"):
            return {"ok": True}, None
        if not isinstance(message.get("date"), int) or abs(time.time() - message["date"]) > 86400:
            return {"ok": True}, None
        return {"ok": True}, {"message_id": str(payload["update_id"]), "sender_id": str(sender["id"]), "receiver_id": str(chat["id"]), "scope": "private", "content": str(message["text"]), "reply_to": str(message["message_id"])}

    async def send_text(self, receiver_id, content, *, reply_to, **kwargs):
        token = self.settings.bot_token.get_secret_value()
        data = await self.json_request("POST", f"https://api.telegram.org/bot{quote(token, safe=':')}/sendMessage", json={"chat_id": receiver_id, "text": content, "reply_parameters": {"message_id": int(reply_to)}})
        if data.get("ok") is False:
            raise ProviderRejected(data.get("error_code", "SEND_REJECTED"))
        if data.get("ok") is not True or not isinstance(data.get("result"), dict) or not data["result"].get("message_id"):
            raise RuntimeError("provider did not confirm a message id")
        return {"success": True, "message_id": str(data["result"]["message_id"])}
