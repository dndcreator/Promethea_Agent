from __future__ import annotations

import uuid
from typing import Any, Dict

from gateway.protocol import GatewayRequest, GatewayResponse

from ..adapter_framework import ChannelAdapter, ChannelMetadata, IdentityContext, PermissionDecision


class TelegramChannelAdapter(ChannelAdapter):
    metadata = ChannelMetadata(
        channel_id="telegram",
        channel_type="im",
        supports_streaming=False,
        supports_attachments=True,
        supports_rich_artifacts=False,
        supports_reactions=True,
        supports_voice=True,
        session_model="per_chat",
    )

    def normalize_identity(self, raw_input: Dict[str, Any]) -> IdentityContext:
        channel_user_id = str(raw_input.get("telegram_user_id") or raw_input.get("sender_id") or "")
        user_id = str(raw_input.get("user_id") or channel_user_id or "telegram_unknown")
        return IdentityContext(
            channel_id=self.metadata.channel_id,
            user_id=user_id,
            channel_user_id=channel_user_id or user_id,
            attributes={"chat_id": raw_input.get("chat_id")},
        )

    def permission_check(self, identity_context: IdentityContext) -> PermissionDecision:
        if not identity_context.channel_user_id:
            return PermissionDecision(allowed=False, reason="missing_telegram_identity")
        return PermissionDecision(allowed=True)

    def build_session_key(self, raw_input: Dict[str, Any]) -> str:
        explicit = str(raw_input.get("session_id") or "").strip()
        if explicit:
            return explicit
        chat_id = str(raw_input.get("chat_id") or "").strip()
        if chat_id:
            return f"tg_chat_{chat_id}"
        uid = str(raw_input.get("telegram_user_id") or raw_input.get("user_id") or "unknown")
        return f"tg_user_{uid}"

    def ingest_message(self, raw_input: Dict[str, Any]) -> GatewayRequest:
        identity = self.normalize_identity(raw_input)
        request_id = str(raw_input.get("request_id") or f"req_{uuid.uuid4().hex}")
        trace_id = str(raw_input.get("trace_id") or f"trace_{request_id}")
        return GatewayRequest(
            request_id=request_id,
            trace_id=trace_id,
            session_id=self.build_session_key(raw_input),
            user_id=identity.user_id,
            channel_id=self.metadata.channel_id,
            input_text=str(raw_input.get("message") or raw_input.get("input_text") or ""),
            input_payload=dict(raw_input),
            metadata=dict(raw_input.get("metadata") or {}),
            requested_mode=raw_input.get("requested_mode"),
            requested_skill=raw_input.get("requested_skill"),
        )

    def emit_response(self, gateway_response: GatewayResponse | Dict[str, Any]) -> Dict[str, Any]:
        payload = gateway_response.to_payload() if isinstance(gateway_response, GatewayResponse) else dict(gateway_response or {})
        payload.setdefault("channel", self.metadata.channel_id)
        payload.setdefault("message_type", "text")
        return payload

    def emit_stream_chunk(self, chunk: str) -> Dict[str, Any]:
        return {"channel": self.metadata.channel_id, "message_type": "text", "content": str(chunk or "")}
