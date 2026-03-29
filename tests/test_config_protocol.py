from gateway.config_protocol import normalize_config_update_params


def test_normalize_config_update_params_accepts_updates_alias():
    out = normalize_config_update_params(
        {
            "config": {"memory": {"enabled": False}},
            "updates": {"memory": {"profile": "balanced"}},
        }
    )
    assert out["config"]["memory"]["enabled"] is False
    assert out["config"]["memory"]["profile"] == "balanced"
