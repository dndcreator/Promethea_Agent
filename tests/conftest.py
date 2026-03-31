"""Shared pytest fixtures and test-environment normalization for this repo."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTEST_SESSION_TMP = PROJECT_ROOT / "_pytest_session_tmp"
PYTEST_CASE_TMP = PROJECT_ROOT / "_pytest_case_tmp"

sys.path.insert(0, str(PROJECT_ROOT))


def _force_repo_local_temp_dirs() -> None:
    """Force all temp artifacts to stay inside repository workspace."""
    PYTEST_SESSION_TMP.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(PYTEST_SESSION_TMP)
    os.environ["TMP"] = str(PYTEST_SESSION_TMP)
    os.environ["TMPDIR"] = str(PYTEST_SESSION_TMP)
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(PYTEST_SESSION_TMP)
    tempfile.tempdir = str(PYTEST_SESSION_TMP)


def _patch_pytest_cleanup_guard() -> None:
    """Ignore cleanup-only PermissionError on Windows temp symlink scan."""
    try:
        import _pytest.pathlib as _pytest_pathlib

        original = _pytest_pathlib.cleanup_dead_symlinks

        def _safe_cleanup_dead_symlinks(root):
            try:
                original(root)
            except PermissionError:
                return

        _pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
    except Exception:
        return


_force_repo_local_temp_dirs()
_patch_pytest_cleanup_guard()


@pytest.fixture
def tmp_path() -> Generator[Path, None, None]:
    """Provide per-test temp path under repository-local `_pytest_case_tmp/`."""
    PYTEST_CASE_TMP.mkdir(parents=True, exist_ok=True)
    case_dir = PYTEST_CASE_TMP / f"case-{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield case_dir
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


@pytest.fixture
def project_root_path() -> Path:
    """Return absolute project root path."""
    return PROJECT_ROOT


@pytest.fixture
def test_config() -> dict:
    """Return a minimal test config object used by multiple unit tests."""
    return {
        "api": {
            "api_key": "test-key",
            "base_url": "https://api.test.com/v1",
            "model": "test-model",
        },
        "memory": {
            "enabled": False,
        },
    }


@pytest.fixture
def mock_event_emitter() -> MagicMock:
    """Provide a generic event emitter mock."""
    emitter = MagicMock()
    emitter.on = MagicMock()
    emitter.emit = MagicMock()
    emitter.off = MagicMock()
    return emitter


@pytest.fixture
def mock_connection_manager() -> MagicMock:
    """Provide a connection manager mock."""
    manager = MagicMock()
    manager.add_connection = MagicMock()
    manager.remove_connection = MagicMock()
    manager.get_connection = MagicMock(return_value=None)
    return manager


@pytest.fixture
def mock_memory_adapter() -> MagicMock:
    """Provide a memory adapter mock with disabled state by default."""
    adapter = MagicMock()
    adapter.is_enabled = MagicMock(return_value=False)
    adapter.add_message = MagicMock(return_value=True)
    adapter.get_context = MagicMock(return_value="")
    return adapter


@pytest.fixture
def mock_message_manager() -> MagicMock:
    """Provide a minimal message manager mock."""
    manager = MagicMock()
    manager.create_session = MagicMock()
    manager.get_session = MagicMock(return_value=None)
    manager.add_message = MagicMock()
    manager.get_recent_messages = MagicMock(return_value=[])
    return manager


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch) -> Generator[None, None, None]:
    """Isolate environment variables per test and set test-mode marker."""
    original_env = os.environ.copy()
    monkeypatch.setenv("PROMETHEA_TEST", "1")
    yield
    os.environ.clear()
    os.environ.update(original_env)
