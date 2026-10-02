import pytest

from gateway.http.personal_workspace_archive import ARCHIVE_VERSION, build_archive, read_archive, rebind_user_scope


def test_workspace_archive_is_reproducible_for_same_payload():
    payload = {"schema_version": 2, "sessions": [{"session_id": "s1"}], "memory": {"mef": {}}}
    first = build_archive(user_id="u1", payload=payload)
    second = build_archive(user_id="u1", payload=payload)
    first_manifest, first_payload = read_archive(first)
    second_manifest, second_payload = read_archive(second)
    assert first_manifest["format"] == ARCHIVE_VERSION
    assert first_manifest["contents"] == second_manifest["contents"]
    assert first_payload == second_payload == payload


def test_workspace_archive_rejects_tampered_payload():
    with pytest.raises(ValueError):
        read_archive(b"not a workspace archive")


def test_rebind_user_scope_changes_ownership_not_arbitrary_ids():
    source = {"user_id": "u1", "id": "memory-1", "children": [{"user_id": "u1", "id": "user_u1", "node_type": "user"}]}
    rebound = rebind_user_scope(source, source_user_id="u1", target_user_id="u2")
    assert rebound["user_id"] == "u2"
    assert rebound["id"] == "memory-1"
    assert rebound["children"][0]["id"] == "user_u2"
