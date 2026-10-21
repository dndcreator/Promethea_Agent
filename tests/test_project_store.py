from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from gateway.http.project_store import ProjectStore
from gateway.http.routes import projects
from gateway.http.routes.auth import get_current_user_id


def test_projects_persist_are_isolated_and_deleting_keeps_sessions_unassigned(tmp_path):
    path = tmp_path / "projects.sqlite3"
    store = ProjectStore(path)
    project = store.create("alice", "Research")
    store.assign("alice", "session-1", project["project_id"])
    assert ProjectStore(path).list("alice")[0]["session_ids"] == ["session-1"]
    assert store.list("bob") == []
    assert not store.rename("bob", project["project_id"], "Stolen")
    assert not store.delete("bob", project["project_id"])
    with pytest.raises(KeyError):
        store.assign("bob", "session-2", project["project_id"])
    assert store.rename("alice", project["project_id"], "Notes")
    assert store.delete("alice", project["project_id"])
    assert store.list("alice") == []


def test_project_archive_import_validates_before_replace_and_filters_memberships(tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    original = store.create("a", "Original")
    with pytest.raises(ValueError):
        store.import_records("a", [{"project_id": "bad", "name": " "}], merge=False, owned_session_ids=set())
    assert store.list("a")[0]["project_id"] == original["project_id"]
    store.import_records("b", [{**original, "session_ids": ["owned", "other"]}], owned_session_ids={"owned"})
    assert store.list("b")[0]["session_ids"] == ["owned"]
    store.assign("b", "owned", None)
    assert store.list("b")[0]["session_ids"] == []
    store.clear_user("b")
    assert store.list("a")


def test_project_import_rejects_malformed_memberships_before_deleting(tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    original = store.create("a", "Original")
    for rows in ([{"project_id": "p", "name": "P", "session_ids": "bad"}], [{"project_id": "p", "name": "P", "session_ids": ["s"]}, {"project_id": "q", "name": "Q", "session_ids": ["s"]}]):
        with pytest.raises(ValueError):
            store.import_records("a", rows, merge=False, owned_session_ids={"s"})
        assert store.list("a")[0]["project_id"] == original["project_id"]


@pytest.mark.asyncio
async def test_workspace_restore_rejects_bad_projects_before_any_writes():
    from gateway.http.routes import personal
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await personal._restore_workspace_payload(gateway_server=SimpleNamespace(), config_service=SimpleNamespace(), user_id="u", payload={"projects": [{"project_id": "p", "name": " "}]}, merge=False)
    assert error.value.status_code == 422


def test_project_routes_enforce_session_and_project_ownership(monkeypatch, tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    owned = store.create("a", "Owned")
    foreign = store.create("b", "Foreign")
    manager = SimpleNamespace(get_session=lambda sid, user_id: {} if sid == "own" and user_id == "a" else None)
    monkeypatch.setattr(projects, "get_gateway_server", lambda: SimpleNamespace(message_manager=manager))
    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[get_current_user_id] = lambda: "a"
    app.dependency_overrides[projects.get_project_store] = lambda: store
    client = TestClient(app)
    assert client.get("/projects").json()["projects"][0]["name"] == "Owned"
    assert client.post("/projects", json={"name": "  "}).status_code == 422
    assert client.post("/projects", json={"name": "New"}).status_code == 201
    assert client.put("/sessions/own/project", json={"project_id": foreign["project_id"]}).status_code == 404
    assert client.put("/sessions/foreign/project", json={"project_id": owned["project_id"]}).status_code == 404
    assert client.put("/sessions/own/project", json={"project_id": owned["project_id"]}).status_code == 204
    assert client.patch(f"/projects/{owned['project_id']}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.delete(f"/projects/{owned['project_id']}").status_code == 204
    assert manager.get_session("own", user_id="a") == {}
