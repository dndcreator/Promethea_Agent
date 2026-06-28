from pathlib import Path

from gateway import user_secrets


def test_ensure_user_secrets_copies_root_env_without_overwriting(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    root_env.write_text(
        "API__API_KEY=root-key\nAPI__BASE_URL=https://example.test/v1\nAPI__MODEL=test-model\n",
        encoding="utf-8",
    )
    users_dir = tmp_path / "config" / "users"

    monkeypatch.setattr(user_secrets, "ENV_FILE", root_env)
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", users_dir)

    path = user_secrets.ensure_user_secrets("u1")
    text = path.read_text(encoding="utf-8")

    assert "API__API_KEY=root-key" in text
    assert "API__BASE_URL=https://example.test/v1" in text
    assert "API__MODEL=test-model" in text

    path.write_text("API__API_KEY=custom\n", encoding="utf-8")
    user_secrets.ensure_user_secrets("u1")

    assert path.read_text(encoding="utf-8") == "API__API_KEY=custom\n"


def test_resolve_llm_runtime_settings_prefers_user_secrets(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    root_env.write_text(
        "API__API_KEY=root-key\nAPI__BASE_URL=https://root.test/v1\nAPI__MODEL=root-model\n",
        encoding="utf-8",
    )
    users_dir = tmp_path / "config" / "users"
    user_dir = users_dir / "u2"
    user_dir.mkdir(parents=True)
    (user_dir / "secrets.env").write_text(
        "API__API_KEY=user-key\nAPI__BASE_URL=https://user.test/v1\nAPI__MODEL=user-model\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(user_secrets, "ENV_FILE", root_env)
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", users_dir)

    resolved = user_secrets.resolve_llm_runtime_settings(
        "u2",
        behavior_config={"api": {"temperature": 0.2, "max_tokens": 123}},
    )

    assert resolved["api_key"] == "user-key"
    assert resolved["base_url"] == "https://user.test/v1"
    assert resolved["model"] == "user-model"
    assert resolved["temperature"] == 0.2
    assert resolved["max_tokens"] == 123


def test_update_user_secrets_does_not_clear_on_empty_input(tmp_path, monkeypatch):
    users_dir = tmp_path / "config" / "users"
    user_dir = users_dir / "u3"
    user_dir.mkdir(parents=True)
    path = user_dir / "secrets.env"
    path.write_text("API__API_KEY=existing\nAPI__MODEL=old-model\n", encoding="utf-8")

    monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", users_dir)

    user_secrets.update_user_secrets(
        "u3",
        {
            "API__API_KEY": "",
            "API__MODEL": "new-model",
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "API__API_KEY=existing" in text
    assert "API__MODEL=new-model" in text
