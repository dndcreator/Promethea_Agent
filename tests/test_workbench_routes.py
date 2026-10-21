from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.http.routes import workbench
from gateway.http.routes.auth import get_current_user_id
from gateway.workspace_service import WorkspaceService


def test_workbench_artifact_preview_is_owner_scoped(monkeypatch, tmp_path):
    workspace_service = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    handle = workspace_service.resolve_workspace_handle(user_id="u1", workspace_id="session-1")
    workspace_service.create_document(
        handle=handle,
        relative_path="draft.md",
        content="# Draft",
        requester_user_id="u1",
    )
    monkeypatch.setattr(
        workbench,
        "get_gateway_server",
        lambda: SimpleNamespace(workspace_service=workspace_service),
    )

    app = FastAPI()
    app.include_router(workbench.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    client = TestClient(app)

    response = client.get(
        "/workbench/artifact",
        params={"workspace_id": "session-1", "path": "draft.md"},
    )
    assert response.status_code == 200
    assert response.text == "# Draft"
    assert response.headers["content-disposition"].startswith("inline;")

    escaped = client.get(
        "/workbench/artifact",
        params={"workspace_id": "session-1", "path": "../other/secret.txt"},
    )
    assert escaped.status_code == 403

    workspace_service.create_document(
        handle=handle, relative_path="page.html", content="<script>alert(1)</script>", requester_user_id="u1",
    )
    active = client.get("/workbench/artifact", params={"workspace_id": "session-1", "path": "page.html"})
    assert active.status_code == 200
    assert active.headers["content-disposition"].startswith("attachment;")
    assert active.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert active.headers["x-content-type-options"] == "nosniff"
