import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from computer.execution_context import ComputerWorkspace
from gateway.http.routes import canvas
from gateway.http.routes.auth import get_current_user_id
from gateway.http.routes.canvas import _preview_headers, _rewrite_location


def test_canvas_csp_keeps_preview_in_an_opaque_origin():
    policy = _preview_headers()["Content-Security-Policy"]
    assert policy.startswith("sandbox allow-scripts allow-forms allow-modals;")
    assert "allow-same-origin" not in policy
    assert "allow-top-navigation" not in policy


def test_canvas_redirect_stays_inside_authenticated_proxy():
    assert _rewrite_location(
        "http://127.0.0.1:8123/editor?doc=1",
        port=8123,
        workspace_id="ws1",
        environment_id="env1",
    ) == "/api/canvas/ws1/env1/preview/editor?doc=1"


def test_canvas_rejects_external_redirects():
    with pytest.raises(HTTPException, match="external redirect"):
        _rewrite_location(
            "https://example.com/escape",
            port=8123,
            workspace_id="ws1",
            environment_id="env1",
        )


def test_static_canvas_route_is_isolated_and_read_only(monkeypatch, tmp_path):
    root = tmp_path / "draft"
    root.mkdir()
    (root / "index.html").write_text("<h1>Draft</h1>", encoding="utf-8")

    async def environment(user_id, workspace_id, environment_id):
        assert user_id == "u1"
        return ComputerWorkspace("u1", workspace_id, tmp_path), {
            "environment_id": environment_id,
            "kind": "static",
            "root": "draft",
            "entrypoint": "index.html",
            "status": "running",
        }

    monkeypatch.setattr(canvas, "_environment", environment)
    app = FastAPI()
    app.include_router(canvas.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    client = TestClient(app)

    response = client.get("/canvas/ws1/env1/preview/")
    assert response.status_code == 200
    assert response.text == "<h1>Draft</h1>"
    assert response.headers["content-security-policy"].startswith("sandbox ")

    rejected = client.post("/canvas/ws1/env1/preview/", content="not allowed")
    assert rejected.status_code == 405
