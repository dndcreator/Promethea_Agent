"""
测试配置和共享 fixtures
"""
import os
import sys
from pathlib import Path
from typing import Generator

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def project_root_path():
    """项目根目录路径"""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def test_config():
    """测试配置"""
    return {
        "api": {
            "api_key": "test-key",
            "base_url": "https://api.test.com/v1",
            "model": "test-model"
        },
        "memory": {
            "enabled": False  # 默认禁用记忆系统，避免需要 Neo4j
        }
    }


@pytest.fixture
def mock_event_emitter():
    """模拟事件发射器"""
    emitter = MagicMock()
    emitter.on = MagicMock()
    emitter.emit = MagicMock()
    emitter.off = MagicMock()
    return emitter


@pytest.fixture
def mock_connection_manager():
    """模拟连接管理器"""
    manager = MagicMock()
    manager.add_connection = MagicMock()
    manager.remove_connection = MagicMock()
    manager.get_connection = MagicMock(return_value=None)
    return manager


@pytest.fixture
def mock_memory_adapter():
    """模拟记忆适配器"""
    adapter = MagicMock()
    adapter.is_enabled = MagicMock(return_value=False)
    adapter.add_message = MagicMock(return_value=True)
    adapter.get_context = MagicMock(return_value="")
    return adapter


@pytest.fixture
def mock_message_manager():
    """模拟消息管理器"""
    manager = MagicMock()
    manager.create_session = MagicMock()
    manager.get_session = MagicMock(return_value=None)
    manager.add_message = MagicMock()
    manager.get_recent_messages = MagicMock(return_value=[])
    return manager


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch):
    """每个测试前重置环境变量"""
    # 保存原始环境变量
    original_env = os.environ.copy()
    
    # 设置测试环境变量
    monkeypatch.setenv("PROMETHEA_TEST", "1")
    
    yield
    
    # 恢复原始环境变量
    os.environ.clear()
    os.environ.update(original_env)
