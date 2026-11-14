"""Shared pytest fixtures and test-environment normalization for this repo."""

from __future__ import annotations

import os
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _test_run_parent() -> Path:
    default = PROJECT_ROOT / ".tmp" / "pytest-runtime"
    requested = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", str(default))).resolve()
    parent = requested if PROJECT_ROOT in requested.parents else default.resolve()
    if PROJECT_ROOT not in parent.parents:
        raise pytest.UsageError("pytest temporary storage must stay inside the checkout")
    return parent


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Give each pytest invocation a private, checkout-local scratch tree."""
    parent = _test_run_parent()
    if config.option.basetemp:
        explicit = Path(config.option.basetemp).resolve()
        scratch = (PROJECT_ROOT / ".tmp").resolve()
        if (
            PROJECT_ROOT not in scratch.parents
            or scratch not in explicit.parents
            or explicit.exists()
            or explicit == parent
            or explicit in parent.parents
        ):
            raise pytest.UsageError("--basetemp must be a new directory under checkout .tmp")
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    temp = run / "session"
    temp.mkdir()
    config.add_cleanup(lambda: shutil.rmtree(run, ignore_errors=True))

    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    patch.setenv("PROMETHEA_TEST_TMP_ROOT", str(run))
    for key in ("TEMP", "TMP", "TMPDIR", "PYTEST_DEBUG_TEMPROOT"):
        patch.setenv(key, str(temp))
    patch.setattr(tempfile, "tempdir", str(temp))


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


_patch_pytest_cleanup_guard()


def pytest_collection_modifyitems(items):
    """Conservative file-level classification; mixed service files stay integration."""
    manifest = json.loads((PROJECT_ROOT / "tests/evaluation/suites.json").read_text(encoding="utf-8"))
    unit_files = set(manifest["unit"])
    for item in items:
        path = Path(str(item.path)).relative_to(PROJECT_ROOT).as_posix()
        if path.startswith("tests/live/"):
            item.add_marker(pytest.mark.live)
        elif "browser" in Path(path).stem:
            item.add_marker(pytest.mark.system)
            item.add_marker(pytest.mark.browser)
        elif path.startswith("tests/system/"):
            item.add_marker(pytest.mark.system)
        else:
            item.add_marker(pytest.mark.unit if path in unit_files else pytest.mark.integration)


@pytest.fixture
def tmp_path() -> Generator[Path, None, None]:
    """Provide per-test temp path under repository-local `.tmp/pytest-runtime/`."""
    case_dir = Path(os.environ["PROMETHEA_TEST_TMP_ROOT"]) / "cases" / f"case-{uuid.uuid4().hex}"
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
