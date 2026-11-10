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


def test_chat_preserves_canonical_options_without_trusting_extra_identity():
    value = validate_gateway_request_params(RequestType.CHAT, {
        "message": "delegate", "metadata": {"multi_agent": True}, "task_id": "task-1",
        "attachments": [{"file_id": "file-1"}], "user_id": "forged",
    })
    assert value["metadata"] == {"multi_agent": True}
    assert value["task_id"] == "task-1" and value["attachments"][0]["file_id"] == "file-1"
    assert "user_id" not in value
