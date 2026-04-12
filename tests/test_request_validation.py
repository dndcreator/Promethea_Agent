from gateway.protocol import RequestType
from gateway.request_validation import validate_gateway_request_params


def test_request_validation_known_method_parses_schema():
    payload = validate_gateway_request_params(
        RequestType.SEND,
        {
            "session_id": "s1",
            "sender": "u1",
            "target": "agent",
            "channel": "web",
            "content": "hello",
        },
    )
    assert payload["target"] == "agent"
    assert payload["content"] == "hello"


def test_request_validation_unknown_method_passthrough():
    src = {"x": 1, "y": "z"}
    out = validate_gateway_request_params(RequestType.STATUS, dict(src))
    assert out == src
