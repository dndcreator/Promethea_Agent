"""Shared transport-only lifecycle for authenticated webhook bot plugins."""
from __future__ import annotations

import aiohttp

from .base import BaseChannel, ChannelConfig, MessageType


class ProviderRejected(RuntimeError):
    def __init__(self, code):
        self.code = str(code)[:100]
        super().__init__(f"Provider rejected request ({self.code})")


class WebhookChannel(BaseChannel):
    reply_window_s = None

    def __init__(self, name, kind, settings):
        super().__init__(name, kind, ChannelConfig(enabled=settings.enabled))
        self.settings = settings
        self.session = None

    def protocol_adapter(self):
        from .adapters.http_adapter import HttpApiChannelAdapter
        from .adapter_framework import ChannelMetadata
        adapter = HttpApiChannelAdapter()
        adapter.metadata = ChannelMetadata(channel_id=self.channel_name, channel_type="im", session_model="per_bound_sender")
        return adapter

    def accept_request(self, headers, body, query):
        return self.accept_webhook(headers, body)

    def verify_webhook(self, query):
        raise ValueError("This channel has no GET verification handshake")

    async def connect(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout_s), trust_env=False)
        self.is_connected = True
        return True

    async def disconnect(self):
        if self.session:
            await self.session.close()
        self.session = None
        self.is_connected = False
        return True

    async def json_request(self, method, url, **kwargs):
        if self.session is None:
            raise RuntimeError("channel not started")
        # Never follow a provider redirect with credentials, or replay a POST.
        async with self.session.request(method, url, allow_redirects=False, **kwargs) as response:
            if response.status >= 300:
                if response.status >= 500:
                    raise RuntimeError("provider request outcome is uncertain")
                raise ProviderRejected(f"HTTP_{response.status}")
            body = await response.content.read(1_000_001)
            if len(body) > 1_000_000:
                raise RuntimeError("provider response exceeds limit")
            import json
            result = json.loads(body)
            if not isinstance(result, dict):
                raise RuntimeError("invalid provider response")
            return result

    async def send_card(self, receiver_id, card_data, **kwargs):
        raise NotImplementedError("this channel exposes text replies only")

    async def get_user_info(self, user_id):
        return None

    async def send_message(self, receiver_id, content, message_type=MessageType.TEXT, **kwargs):
        if message_type != MessageType.TEXT:
            raise ValueError("only text messages are supported")
        return await self.send_text(receiver_id, content, **kwargs)
