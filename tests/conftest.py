"""
?fixtures
"""
import os
import sys
from pathlib import Path
from typing import Generator

# TODO: comment cleaned
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def project_root_path():
    """TODO: add docstring."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def test_config():
    """TODO: add docstring."""
    return {
        "api": {
            "api_key": "test-key",
            "base_url": "https://api.test.com/v1",
            "model": "test-model"
        },
        "memory": {
            "enabled": False  # TODO: comment cleaned
        }
    }


@pytest.fixture
def mock_event_emitter():
    """TODO: add docstring."""
    emitter = MagicMock()
    emitter.on = MagicMock()
    emitter.emit = MagicMock()
    emitter.off = MagicMock()
    return emitter


@pytest.fixture
def mock_connection_manager():
    """TODO: add docstring."""
    manager = MagicMock()
    manager.add_connection = MagicMock()
    manager.remove_connection = MagicMock()
    manager.get_connection = MagicMock(return_value=None)
    return manager


@pytest.fixture
def mock_memory_adapter():
    """TODO: add docstring."""
    adapter = MagicMock()
    adapter.is_enabled = MagicMock(return_value=False)
    adapter.add_message = MagicMock(return_value=True)
    adapter.get_context = MagicMock(return_value="")
    return adapter


@pytest.fixture
def mock_message_manager():
    """TODO: add docstring."""
    manager = MagicMock()
    manager.create_session = MagicMock()
    manager.get_session = MagicMock(return_value=None)
    manager.add_message = MagicMock()
    manager.get_recent_messages = MagicMock(return_value=[])
    return manager


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch):
    """TODO: add docstring."""
    # TODO: comment cleaned
    original_env = os.environ.copy()
    
    # TODO: comment cleaned
    monkeypatch.setenv("PROMETHEA_TEST", "1")
    
    yield
    
    # TODO: comment cleaned
    os.environ.clear()
    os.environ.update(original_env)

