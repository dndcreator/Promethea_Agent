"""
ConfigService 
?
"""
import pytest
from unittest.mock import MagicMock, patch
from gateway.config_service import ConfigService
from gateway.events import EventEmitter


class TestConfigService:
    """TODO: add docstring."""
    
    def test_init(self):
        """TODO: add docstring."""
        service = ConfigService()
        assert service is not None
        assert service._default_config is not None
    
    def test_get_default_config(self):
        """TODO: add docstring."""
        service = ConfigService()
        config = service.get_default_config()
        assert config is not None
        assert hasattr(config, 'api')
        assert hasattr(config, 'memory')
    
    def test_get_user_config_no_user(self):
        """TODO: add docstring."""
        service = ConfigService()
        config = service.get_user_config()
        assert isinstance(config, dict)
    
    def test_get_merged_config(self):
        """TODO: add docstring."""
        service = ConfigService()
        merged = service.get_merged_config()
        assert isinstance(merged, dict)
        assert 'api' in merged
        assert 'memory' in merged
    
    @pytest.mark.asyncio
    async def test_reload_default_config(self):
        """TODO: add docstring."""
        service = ConfigService(event_emitter=EventEmitter())
        result = await service.reload_default_config()
        assert result['success'] is True
    
    @pytest.mark.asyncio
    async def test_update_user_config(self):
        """TODO: add docstring."""
        service = ConfigService(event_emitter=EventEmitter())
        
        # Mock user_manager
        with patch('gateway.config_service.user_manager') as mock_user_manager:
            mock_user_manager.update_user_config_file.return_value = True
            
            from gateway.protocol import ConfigUpdateParams
            params = ConfigUpdateParams(config_data={"api": {"model": "gpt-4"}})
            
            result = await service.update_user_config(params, user_id="test_user")
            assert result['success'] is True
    
    @pytest.mark.asyncio
    async def test_switch_model(self, tmp_path, monkeypatch):
        """TODO: add docstring."""
        from gateway import user_secrets

        monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / ".env")
        monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", tmp_path / "users")
        service = ConfigService(event_emitter=EventEmitter())
        
        with patch('gateway.config_service.user_manager') as mock_user_manager:
            mock_user_manager.update_user_config_file.return_value = True
            
            from gateway.protocol import ConfigSwitchModelParams
            params = ConfigSwitchModelParams(model="gpt-4")
            
            result = await service.switch_model(params, user_id="test_user")
            assert result['success'] is True

    @pytest.mark.asyncio
    async def test_update_user_config_ignores_env_only_secret_fields(self):
        service = ConfigService(event_emitter=EventEmitter())

        with patch('gateway.config_service.user_manager') as mock_user_manager:
            mock_user_manager.get_user_config.return_value = {"agent_name": "Promethea"}
            mock_user_manager.update_user_config_file.return_value = True

            result = await service.update_user_config(
                "test_user",
                {
                    "api": {"api_key": "sk-xxx", "model": "gpt-4.1-mini"},
                    "memory": {
                        "neo4j": {"password": "secret"},
                        "api": {"api_key": "mem-secret"},
                    },
                },
                validate=False,
            )

            assert result["success"] is True
            called_args = mock_user_manager.update_user_config_file.call_args[0]
            persisted = called_args[1]
            assert persisted.get("config_version")
            assert persisted.get("api", {}).get("api_key") is None
            assert persisted.get("memory", {}).get("neo4j", {}).get("password") is None
            assert persisted.get("memory", {}).get("api", {}).get("api_key") is None
            assert persisted.get("api", {}).get("model") is None
            assert any("sensitive env field ignored" in w for w in result.get("warnings", []))

    def test_get_merged_config_pins_env_only_secrets(self):
        service = ConfigService()
        default_payload = service.get_default_config().model_dump()

        with patch("gateway.config_service.user_manager") as mock_user_manager:
            mock_user_manager.get_user_config.return_value = {
                "api": {"api_key": "user-should-not-win"},
                "memory": {
                    "api": {"api_key": "mem-user-should-not-win"},
                    "neo4j": {"password": "neo-user-should-not-win"},
                },
            }
            merged = service.get_merged_config("test_user")

        assert merged["api"]["api_key"] == default_payload["api"]["api_key"]
        assert merged["memory"]["api"]["api_key"] == default_payload["memory"]["api"]["api_key"]
        assert merged["memory"]["neo4j"]["password"] == default_payload["memory"]["neo4j"]["password"]

    def test_get_effective_config_with_sources_marks_user_and_env_paths(self):
        service = ConfigService()
        with patch("gateway.config_service.user_manager") as mock_user_manager:
            mock_user_manager.get_user_config.return_value = {
                "api": {"model": "my-model", "api_key": "cannot-win"},
                "system": {"stream_mode": False},
            }
            payload = service.get_effective_config_with_sources(
                "test_user",
                field_paths=["api.model", "api.api_key", "system.stream_mode"],
            )

        sources = payload.get("sources") or {}
        assert sources.get("api.model") == "env_only_secret"
        assert sources.get("api.api_key") == "env_only_secret"
        assert sources.get("system.stream_mode") == "user_override"



    @pytest.mark.asyncio
    async def test_update_user_config_merges_canonical_and_legacy_param_shapes(self):
        service = ConfigService(event_emitter=EventEmitter())

        with patch("gateway.config_service.user_manager") as mock_user_manager:
            mock_user_manager.get_user_config.return_value = {"agent_name": "Promethea"}
            mock_user_manager.update_user_config_file.return_value = True

            from gateway.protocol import ConfigUpdateParams
            params = ConfigUpdateParams(
                config_data={"memory": {"enabled": False}},
                config={"memory": {"profile": "balanced"}},
            )

            result = await service.update_user_config(params, user_id="test_user", validate=False)
            assert result["success"] is True
            persisted = mock_user_manager.update_user_config_file.call_args[0][1]
            assert persisted.get("memory", {}).get("enabled") is False
            assert persisted.get("memory", {}).get("profile") == "balanced"
