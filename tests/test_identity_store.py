from gateway.http.identity_store import IdentityStore


def _legacy_user(user_id: str = "u1", username: str = "alice"):
    return {
        "id": f"user_{user_id}",
        "user_id": user_id,
        "username": username,
        "password_hash": "hash",
        "agent_name": "EDI",
        "system_prompt": "core",
        "created_at": "2026-01-01T00:00:00Z",
        "channel_web": "account-1",
    }


def test_identity_store_import_is_idempotent_and_backend_independent(tmp_path):
    store = IdentityStore(tmp_path / "identity.sqlite3")

    first = store.import_legacy([_legacy_user()])
    second = store.import_legacy([_legacy_user()])

    assert first == {"imported": 1, "existing": 0, "conflicts": 0}
    assert second == {"imported": 0, "existing": 1, "conflicts": 0}
    assert store.get_by_username("alice")["user_id"] == "u1"


def test_identity_store_preserves_profile_and_channel_bindings(tmp_path):
    store = IdentityStore(tmp_path / "identity.sqlite3")
    store.create(_legacy_user())

    assert store.update_profile("user_u1", agent_name="Normandy") is True
    assert store.bind_channel("u1", "web", "account-1") is True

    assert store.get_by_id("u1")["agent_name"] == "Normandy"
    assert store.get_channels("user_u1") == {"web": "account-1"}
    assert store.get_by_channel("web", "account-1")["username"] == "alice"


def test_identity_store_reports_legacy_name_or_id_conflicts(tmp_path):
    store = IdentityStore(tmp_path / "identity.sqlite3")
    store.create(_legacy_user())

    result = store.import_legacy([_legacy_user(user_id="u2", username="alice")])

    assert result == {"imported": 0, "existing": 0, "conflicts": 1}
    assert store.get_by_username("alice")["user_id"] == "u1"
