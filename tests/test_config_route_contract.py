from gateway.http.routes.config import (
    ConfigUpdateOptions,
    ConfigUpdateRequest,
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
    assert "api.api_key" in contract["env_only_secret_paths"]
    assert "memory.enabled" in contract["ui_profiles"]["simple_fields"]
