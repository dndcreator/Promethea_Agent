from gateway.http.user_manager import UserManager


def test_build_user_default_config_uses_template_and_strips_env_only_secrets():
    payload = UserManager._build_user_default_config("Alice")

    assert payload.get("agent_name") == "Alice"
    assert payload.get("api", {}).get("api_key") is None
    assert payload.get("memory", {}).get("api", {}).get("api_key") is None
    assert payload.get("memory", {}).get("neo4j", {}).get("password") is None
    assert payload.get("system") is not None
