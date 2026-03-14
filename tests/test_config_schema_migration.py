from unittest.mock import patch

from gateway.config_migrations import CURRENT_CONFIG_VERSION, migrate_config
from gateway.config_service import ConfigService


def test_migrate_legacy_config_adds_config_version_and_sections():
    legacy = {
        "system": {"version": "1.0", "stream_mode": True},
        "api": {"model": "gpt-4"},
        "reasoning": {"mode": "react_tot"},
    }

    migrated, report = migrate_config(legacy)

    assert migrated.get("config_version") == CURRENT_CONFIG_VERSION
    assert isinstance(migrated.get("runtime_config"), dict)
    assert isinstance(migrated.get("user_preferences"), dict)
    assert isinstance(migrated.get("security_config"), dict)
    assert "0->1" in report.get("applied_steps", [])


def test_config_service_scoped_runtime_query_returns_only_requested_scope():
    service = ConfigService()
    payload = service.get_runtime_config(user_id=None, scope="api")

    assert isinstance(payload, dict)
    assert "model" in payload
    assert "base_url" in payload


def test_config_service_user_preferences_scoped_query():
    service = ConfigService()
    with patch("gateway.config_service.user_manager") as mock_user_manager:
        mock_user_manager.get_user_config.return_value = {
            "agent_name": "Promethea",
            "system_prompt": "Hi",
            "config_version": "1",
            "user_preferences": {
                "default_mode": "deep",
                "preferred_skills": ["coding_copilot"],
            },
        }
        prefs = service.get_user_preferences("u1", scope="user_preferences")

    assert prefs.get("default_mode") == "deep"
    assert "coding_copilot" in prefs.get("preferred_skills", [])


def test_update_user_config_persists_config_version():
    service = ConfigService()

    with patch("gateway.config_service.user_manager") as mock_user_manager:
        mock_user_manager.get_user_config.return_value = {"agent_name": "Promethea"}
        mock_user_manager.update_user_config_file.return_value = True

        import asyncio

        result = asyncio.run(
            service.update_user_config(
                "u1",
                {"api": {"model": "gpt-4"}},
                validate=False,
            )
        )

        assert result.get("success") is True
        called_args = mock_user_manager.update_user_config_file.call_args[0]
        assert called_args[0] == "u1"
        persisted = called_args[1]
        assert persisted.get("config_version") == CURRENT_CONFIG_VERSION
