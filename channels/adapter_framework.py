from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from gateway.protocol import GatewayRequest, GatewayResponse


class IdentityContext(BaseModel):
    channel_id: str
    user_id: str
    channel_user_id: Optional[str] = None
    roles: list[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str = "allowed"


class ChannelMetadata(BaseModel):
    channel_id: str
    channel_type: str
    supports_streaming: bool = False
    supports_attachments: bool = False
    supports_rich_artifacts: bool = False
    supports_reactions: bool = False
    supports_voice: bool = False
    session_model: str = "per_user"


class ChannelAdapter(ABC):
    metadata: ChannelMetadata

    @abstractmethod
    def ingest_message(self, raw_input: Dict[str, Any]) -> GatewayRequest:
        raise NotImplementedError

    @abstractmethod
    def normalize_identity(self, raw_input: Dict[str, Any]) -> IdentityContext:
        raise NotImplementedError

    @abstractmethod
    def build_session_key(self, raw_input: Dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def emit_response(self, gateway_response: GatewayResponse | Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def emit_stream_chunk(self, chunk: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def permission_check(self, identity_context: IdentityContext) -> PermissionDecision:
        raise NotImplementedError
