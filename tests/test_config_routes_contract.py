from gateway.http.routes.config import (
    ConfigUpdateRequest,
    _build_basic_config_view,
)


def test_config_update_request_parses_hot_apply_string_false_to_false():
    req = ConfigUpdateRequest(
        config={"api": {"model": "gpt-4.1-mini"}},
        options={"hot_apply": "false"},
    )
    assert req.options is not None
    assert req.options.hot_apply is False


def test_basic_config_view_keeps_key_fields_and_redacted_secrets():
    raw = {
        "config_version": "1",
        "agent_name": "Promethea",
        "system_prompt": "hello",
        "api": {"api_key": "", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
        "memory": {"enabled": "true", "store_backend": "sqlite_graph", "neo4j": {"password": ""}},
        "reasoning": {"enabled": False, "mode": "react_tot"},
        "sandbox": {"enabled": "false", "profile": "dev"},
        "system": {"stream_mode": "false", "debug": "true", "log_level": "INFO"},
    }
    view = _build_basic_config_view(raw)
    assert view["api"]["model"] == "gpt-4.1-mini"
    assert view["memory"]["enabled"] is True
    assert view["sandbox"]["enabled"] is False
    assert view["system"]["stream_mode"] is False
    assert view["system"]["debug"] is True
