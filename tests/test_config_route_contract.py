from gateway.http.routes.config import (
    ConfigUpdateOptions,
    ConfigUpdateRequest,
    _build_basic_config_view,
    _build_config_contract,
    _normalize_config_update_request,
)


def test_normalize_config_update_request_accepts_legacy_aliases():
    req = ConfigUpdateRequest(
        config_data={"memory": {"enabled": False, "profile": "balanced"}},
        config={"memory": {"enabled": True}},
        hot_reload=True,
        validate_config=False,
    )

    out = _normalize_config_update_request(req)
    assert out["config"]["memory"]["enabled"] is True
    assert out["config"]["memory"]["profile"] == "balanced"
    assert out["hot_apply"] is True
    assert out["validate"] is False


def test_normalize_config_update_request_prefers_options_hot_apply():
    req = ConfigUpdateRequest(
        config={"system": {"stream_mode": True}},
        options=ConfigUpdateOptions(hot_apply=False),
        hot_reload=True,
    )
    out = _normalize_config_update_request(req)
    assert out["hot_apply"] is False
    assert out["validate"] is True


def test_build_config_contract_shape():
    payload = _build_config_contract()
    contract = payload["contract"]

    assert payload["status"] == "success"
    assert contract["name"] == "promethea_config_contract"
    assert "/api/config/update" == contract["update_api"]["path"]
    assert "/api/config/default-template" == contract["template_api"]["path"]
    assert "/api/config/effective" == contract["effective_api"]["path"]
    assert "/api/config/ui-schema" == contract["ui_schema_api"]["path"]
    assert "api.api_key" in contract["env_only_secret_paths"]
    assert "memory.enabled" in contract["ui_profiles"]["simple_fields"]


def test_basic_config_view_excludes_api_fields_for_simple_ui():
    out = _build_basic_config_view(
        {
            "config_version": "1",
            "agent_name": "Promethea",
            "system_prompt": "x",
            "api": {"model": "gpt-x", "base_url": "https://x", "api_key": "secret"},
            "memory": {"enabled": True, "profile": "balanced", "store_backend": "neo4j"},
            "reasoning": {"enabled": False, "mode": "react_tot"},
            "system": {"stream_mode": True},
        }
    )
    assert "api" not in out
    assert out["memory"]["enabled"] is True


def test_basic_config_view_defaults_to_enabled_for_memory_and_reasoning():
    out = _build_basic_config_view(
        {
            "config_version": "1",
            "agent_name": "Promethea",
            "system_prompt": "",
            "memory": {},
            "reasoning": {},
            "system": {},
        }
    )
    assert out["memory"]["enabled"] is True
    assert out["reasoning"]["enabled"] is True
