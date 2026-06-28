import json

from gateway.http.user_manager import UserManager


def _make_manager(tmp_path):
    mgr = object.__new__(UserManager)
    mgr.users_dir = tmp_path / "users"
    mgr.users_dir.mkdir(parents=True, exist_ok=True)
    mgr.store_backend = "sqlite_graph"
    mgr.connector = None
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


def test_user_default_config_does_not_persist_model_routing(monkeypatch):
    class _Config:
        def model_dump(self, mode=None):
            return {
                "agent_name": "Promethea",
                "api": {
                    "api_key": "secret",
                    "base_url": "https://provider.example/v1",
                    "model": "provider/model",
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "failover_models": ["fallback/model"],
                },
                "memory": {
                    "api": {
                        "api_key": "memory-secret",
                        "base_url": "https://memory-provider.example/v1",
                        "model": "memory/model",
                    },
                    "neo4j": {"password": "neo4j-secret", "uri": "bolt://localhost:7687"},
                    "cold_layer": {"summary_model": "summary/model", "max_summary_length": 500},
                },
                "persona": {"enabled": True},
            }

    monkeypatch.setattr("gateway.http.user_manager.load_config", lambda: _Config())

    cfg = UserManager._build_user_default_config("Promethea")

    assert "api_key" not in cfg["api"]
    assert "base_url" not in cfg["api"]
    assert "model" not in cfg["api"]
    assert "failover_models" not in cfg["api"]
    assert cfg["api"]["temperature"] == 0.7
    assert "api_key" not in cfg["memory"]["api"]
    assert "base_url" not in cfg["memory"]["api"]
    assert "model" not in cfg["memory"]["api"]
    assert "password" not in cfg["memory"]["neo4j"]
    assert "summary_model" not in cfg["memory"]["cold_layer"]
    assert cfg["persona"]["enabled"] is True


def test_local_user_backend_registers_and_verifies_without_neo4j(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    monkeypatch.setattr(
        UserManager,
        "_build_user_default_config",
        staticmethod(lambda agent_name: {"agent_name": agent_name, "system_prompt": ""}),
    )

    user_id = UserManager.create_user(mgr, "alice", "pw", "Alicia")

    assert user_id
    user = UserManager.verify_user(mgr, "alice", "pw")
    assert user is not None
    assert user["user_id"] == user_id
    assert user["agent_name"] == "Alicia"
    assert (mgr.users_dir / "_local_users.json").exists()
    assert (mgr.users_dir / user_id / "config.json").exists()


def test_local_user_backend_delete_removes_user_and_local_state(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    monkeypatch.setattr(
        UserManager,
        "_build_user_default_config",
        staticmethod(lambda agent_name: {"agent_name": agent_name, "system_prompt": ""}),
    )
    user_id = UserManager.create_user(mgr, "alice", "pw", "Alicia")
    assert user_id
    (tmp_path / "logs" / user_id).mkdir(parents=True)
    (tmp_path / "workspace" / user_id).mkdir(parents=True)
    monkeypatch.setattr(mgr, "_cleanup_project_root", lambda: tmp_path)

    assert UserManager.delete_user(mgr, user_id) is True

    assert UserManager.get_user_by_username(mgr, "alice") is None
    assert not (mgr.users_dir / user_id).exists()
    assert not (tmp_path / "logs" / user_id).exists()
    assert not (tmp_path / "workspace" / user_id).exists()


def test_create_user_config_creates_secrets_without_overwriting_existing(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path)
    user_uuid = "u3"
    existing_dir = mgr.users_dir / user_uuid
    existing_dir.mkdir(parents=True)
    secrets_path = existing_dir / "secrets.env"
    secrets_path.write_text("API__API_KEY=keep-me\n", encoding="utf-8")

    monkeypatch.setattr(
        UserManager,
        "_build_user_default_config",
        staticmethod(lambda agent_name: {"agent_name": agent_name, "api": {"temperature": 0.7}}),
    )

    UserManager.create_user_config(mgr, user_uuid, "A")

    assert json.loads((existing_dir / "config.json").read_text(encoding="utf-8"))["agent_name"] == "A"
    assert secrets_path.read_text(encoding="utf-8") == "API__API_KEY=keep-me\n"


def test_neo4j_backend_without_connector_rejects_registration(tmp_path):
    from memory.neo4j_connector import Neo4jConnectionPool

    Neo4jConnectionPool._last_error = ""
    Neo4jConnectionPool._last_error_code = ""
    mgr = _make_manager(tmp_path)
    mgr.store_backend = "neo4j"
    mgr.connector = None

    assert UserManager.can_register(mgr) == (False, "neo4j_user_backend_unavailable")
    assert UserManager.create_user(mgr, "alice", "pw", "Alicia") is None
