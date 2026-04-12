from types import SimpleNamespace

from gateway.server_runtime_utils import (
    build_run_context,
    resolve_provider_id,
    resolve_request_trace_id,
    resolve_request_user_id,
    resolve_tool_identity,
)


def _fake_request(params=None):
    return SimpleNamespace(id="r1", params=params or {})


def test_server_runtime_identity_helpers():
    conn = SimpleNamespace(identity=SimpleNamespace(device_id="u-dev"))
    req = _fake_request({"user_id": "u-param"})
    assert resolve_request_user_id(conn, req) == "u-dev"
    assert resolve_request_trace_id(_fake_request({"trace_id": "t1"})) == "t1"


def test_server_runtime_context_builder():
    req = _fake_request({"message": "hello", "requested_mode": "react_tot"})
    ctx = build_run_context(
        request=req,
        session_id="s1",
        user_id="u1",
        channel_id="web",
    )
    assert ctx.request_id == "r1"
    assert ctx.session_state.session_id == "s1"
    assert ctx.normalized_input["text"] == "hello"


def test_server_runtime_tool_and_provider_resolution():
    service, tool = resolve_tool_identity("utils.echo", {})
    assert service == "utils" and tool == "echo"
    assert resolve_provider_id({"api": {"base_url": "https://openrouter.ai/api/v1"}}) == "openrouter"
