import json
from pathlib import Path

import pytest

from memory.hippocampus import HippocampusReplayService
from tests.test_hippocampus_replay import _policy


def service(tmp_path):
    return HippocampusReplayService(policy=_policy(tmp_path), select_memories=lambda *_: [], reflect=lambda *_: [], commit_insight=lambda *_: True)


def sharing_violation():
    error = PermissionError("transient sharing denial")
    error.winerror = 32
    return error


def test_atomic_commit_retries_windows_sharing_denial_without_replaying_effects(tmp_path, monkeypatch):
    import memory.hippocampus.replay as replay
    model = service(tmp_path)
    real_replace = replay.os.replace
    attempts, sleeps = [], []
    def replace(source, target):
        attempts.append(Path(source))
        assert json.loads(Path(source).read_text(encoding="utf-8"))["users"]["alice"]["pending_memories"] == 2
        if len(attempts) < 3:
            raise sharing_violation()
        real_replace(source, target)
    monkeypatch.setattr(replay.os, "replace", replace)
    monkeypatch.setattr(replay.time, "sleep", sleeps.append)
    model._user_state("alice")["pending_memories"] = 2
    model._save_state()
    assert len(attempts) == 3 and len(set(attempts)) == 1 and sleeps == [.01, .03]
    assert not attempts[0].exists()
    assert json.loads(model._path.read_text(encoding="utf-8"))["users"]["alice"]["pending_memories"] == 2


@pytest.mark.parametrize("transient", [True, False])
def test_persistent_commit_failure_keeps_previous_state_and_cleans_temp(tmp_path, monkeypatch, transient):
    import memory.hippocampus.replay as replay
    model = service(tmp_path)
    model._save_state()
    original = model._path.read_bytes()
    attempts = []
    def replace(source, target):
        attempts.append(Path(source))
        raise sharing_violation() if transient else PermissionError("persistent policy denial")
    monkeypatch.setattr(replay.os, "replace", replace)
    monkeypatch.setattr(replay.time, "sleep", lambda *_: None)
    with pytest.raises(PermissionError):
        model._save_state()
    assert len(attempts) == (4 if transient else 1)
    assert model._path.read_bytes() == original
    assert not list(tmp_path.glob(".replay_state.json.*.tmp"))
