import json

from gateway.http.user_manager import UserManager


def _make_manager(tmp_path):
    mgr = object.__new__(UserManager)
    mgr.users_dir = tmp_path / "users"
    mgr.users_dir.mkdir(parents=True, exist_ok=True)
    return mgr


def test_get_user_config_auto_heals_corrupt_json(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    user_uuid = "u1"
    current_path = UserManager._current_config_path(mgr, user_uuid)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text('{"config_version":"1","system":{"base_dir":', encoding="utf-8")

    monkeypatch.setattr(mgr, "get_user_by_id", lambda _uid: {"agent_name": "Recovered"})
    monkeypatch.setattr(
        UserManager,
        "_build_user_default_config",
        staticmethod(lambda agent_name: {"agent_name": agent_name, "system_prompt": ""}),
    )

    cfg = UserManager.get_user_config(mgr, user_uuid)

    assert cfg.get("agent_name") == "Recovered"
    assert cfg.get("system_prompt") == ""

    backups = list(current_path.parent.glob("config.corrupt-*.json"))
    assert backups
    assert "base_dir" in backups[0].read_text(encoding="utf-8")
    assert json.loads(current_path.read_text(encoding="utf-8")).get("agent_name") == "Recovered"


def test_update_user_config_file_uses_atomic_writer(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    user_uuid = "u2"
    captured = {}

    monkeypatch.setattr(mgr, "get_user_config", lambda _uid: {"agent_name": "A"})

    def _fake_atomic(path, payload):
        captured["path"] = str(path)
        captured["payload"] = payload

    monkeypatch.setattr(mgr, "_write_json_atomic", _fake_atomic)

    ok = UserManager.update_user_config_file(mgr, user_uuid, {"system_prompt": "hello"})

    assert ok is True
    assert captured["path"].endswith(f"{user_uuid}\\config.json")
    assert captured["payload"].get("system_prompt") == "hello"
