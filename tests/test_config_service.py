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
    async def test_switch_model(self):
        """TODO: add docstring."""
        service = ConfigService(event_emitter=EventEmitter())
        
        with patch('gateway.config_service.user_manager') as mock_user_manager:
            mock_user_manager.update_user_config_file.return_value = True
            
            from gateway.protocol import ConfigSwitchModelParams
            params = ConfigSwitchModelParams(model="gpt-4")
            
            result = await service.switch_model(params, user_id="test_user")
            assert result['success'] is True

