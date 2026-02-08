"""
ConfigService 测试
测试配置服务的核心功能
"""
import pytest
from unittest.mock import MagicMock, patch
from gateway.config_service import ConfigService
from gateway.events import EventEmitter


class TestConfigService:
    """ConfigService 测试类"""
    
    def test_init(self):
        """测试初始化"""
        service = ConfigService()
        assert service is not None
        assert service._default_config is not None
    
    def test_get_default_config(self):
        """测试获取默认配置"""
        service = ConfigService()
        config = service.get_default_config()
        assert config is not None
        assert hasattr(config, 'api')
        assert hasattr(config, 'memory')
    
    def test_get_user_config_no_user(self):
        """测试获取用户配置（无用户）"""
        service = ConfigService()
        config = service.get_user_config()
        assert isinstance(config, dict)
    
    def test_get_merged_config(self):
        """测试获取合并配置"""
        service = ConfigService()
        merged = service.get_merged_config()
        assert isinstance(merged, dict)
        assert 'api' in merged
        assert 'memory' in merged
    
    @pytest.mark.asyncio
    async def test_reload_default_config(self):
        """测试重载默认配置"""
        service = ConfigService(event_emitter=EventEmitter())
        result = await service.reload_default_config()
        assert result['success'] is True
    
    @pytest.mark.asyncio
    async def test_update_user_config(self):
        """测试更新用户配置"""
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
        """测试切换模型"""
        service = ConfigService(event_emitter=EventEmitter())
        
        with patch('gateway.config_service.user_manager') as mock_user_manager:
            mock_user_manager.update_user_config_file.return_value = True
            
            from gateway.protocol import ConfigSwitchModelParams
            params = ConfigSwitchModelParams(model="gpt-4")
            
            result = await service.switch_model(params, user_id="test_user")
            assert result['success'] is True
