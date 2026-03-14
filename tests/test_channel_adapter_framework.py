from channels.adapter_framework import ChannelAdapter, ChannelMetadata
from channels.adapter_registry import build_default_adapter_registry
from channels.adapters.http_adapter import HttpApiChannelAdapter
from channels.adapters.telegram_adapter import TelegramChannelAdapter
from channels.adapters.web_adapter import WebChannelAdapter
from gateway.protocol import GatewayResponse


class _DummyAdapter(ChannelAdapter):
    metadata = ChannelMetadata(channel_id="dummy", channel_type="test")

    def ingest_message(self, raw_input):
        return raw_input

    def normalize_identity(self, raw_input):
        return {"user_id": raw_input.get("user_id")}

    def build_session_key(self, raw_input):
        return "dummy_session"

    def emit_response(self, gateway_response):
        return {"ok": True}

    def emit_stream_chunk(self, chunk):
        return {"chunk": chunk}

    def permission_check(self, identity_context):
        class _Decision:
            allowed = True
            reason = "ok"

        return _Decision()


def test_base_adapter_interface_shape():
    adapter = _DummyAdapter()
    assert adapter.metadata.channel_id == "dummy"
    assert adapter.build_session_key({}) == "dummy_session"


def test_web_adapter_to_gateway_request():
    adapter = WebChannelAdapter()
    req = adapter.ingest_message({"request_id": "r1", "message": "hello", "user_id": "u1"})
    assert req.request_id == "r1"
    assert req.user_id == "u1"
    assert req.input_text == "hello"
    assert req.channel_id == "web"


def test_http_adapter_to_gateway_request():
    adapter = HttpApiChannelAdapter()
    req = adapter.ingest_message({"request_id": "r2", "message": "ping", "user_id": "u2"})
    assert req.request_id == "r2"
    assert req.user_id == "u2"
    assert req.input_text == "ping"
    assert req.channel_id == "http_api"


def test_gateway_response_to_channel_output_mapping():
    adapter = WebChannelAdapter()
    mapped = adapter.emit_response(
        GatewayResponse(request_id="r1", trace_id="t1", session_id="s1", user_id="u1", response_text="ok")
    )
    assert mapped["response_text"] == "ok"
    assert mapped["channel"] == "web"


def test_session_key_rules_across_channels():
    web = WebChannelAdapter()
    http = HttpApiChannelAdapter()
    telegram = TelegramChannelAdapter()

    assert web.build_session_key({"user_id": "u1"}) == "web_u1"
    assert http.build_session_key({"user_id": "u1"}) == "http_u1"
    assert telegram.build_session_key({"chat_id": "42"}) == "tg_chat_42"


def test_identity_normalization_and_permission():
    http = HttpApiChannelAdapter()
    identity = http.normalize_identity({"user_id": "u3"})
    decision = http.permission_check(identity)
    assert identity.user_id == "u3"
    assert decision.allowed is True


def test_new_channel_telegram_adapter_registered():
    registry = build_default_adapter_registry()
    telegram = registry.get("telegram")
    assert telegram is not None
    req = telegram.ingest_message({"message": "hi", "telegram_user_id": "tg_u1", "chat_id": "99"})
    assert req.channel_id == "telegram"
    assert req.session_id == "tg_chat_99"
