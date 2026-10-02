from gateway.config_protocol import normalize_config_update_params


def test_normalize_config_update_params_accepts_canonical_shape():
    out = normalize_config_update_params(
        {
            "config": {"memory": {"enabled": False, "profile": "balanced"}},
            "options": {"hot_apply": True},
            "validate": False,
        }
    )
    assert out["config"]["memory"]["enabled"] is False
    assert out["config"]["memory"]["profile"] == "balanced"
    assert out["hot_apply"] is True
    assert out["validate"] is False
