import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from computer.execution_context import ComputerWorkspace
from gateway.http.routes import canvas
from gateway.http.routes.auth import get_current_user_id
from gateway.http.routes.canvas import _preview_headers, _rewrite_location
from computer.canvas_document import render_canvas_html


def test_canvas_csp_keeps_preview_in_an_opaque_origin():
    policy = _preview_headers()["Content-Security-Policy"]
    assert policy.startswith("sandbox allow-scripts allow-forms allow-modals;")
    assert "allow-same-origin" not in policy
    assert "allow-top-navigation" not in policy
    assert "connect-src 'none'" in policy


@pytest.mark.parametrize("source", [
    '<!doctype html><html><head><style>body{margin:0}</style></head><body>ok</body></html>',
    '<!doctype html>\n<html><head data-app="yes">\n<title>App</title></head><body>ok</body></html>',
])
def test_bridge_precedes_application_scripts_without_corrupting_markup(source):
    rendered = render_canvas_html(source)
    assert rendered.startswith('<!doctype html>')
    before = rendered.index('<script>')
    after = rendered.index('</script>') + len('</script>')
    assert rendered[:before] + rendered[after:] == source
    first_application_tag = '<style>' if '<style>' in source else '<title>'
    assert before < rendered.index(first_application_tag)


def test_local_assets_do_not_require_host_credentials_from_opaque_frame(tmp_path):
    source = '<html><head><link rel="stylesheet" href="app.css"></head><body><img src="icon.svg"><script src="app.js"></script></body></html>'
    (tmp_path / "app.js").write_text("document.body.dataset.ready='yes'", encoding="utf-8")
    (tmp_path / "app.css").write_text("body {color: black}", encoding="utf-8")
    (tmp_path / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    rendered = render_canvas_html(source, root=tmp_path, entrypoint=tmp_path / "index.html")
    assert "src=\"app.js\"" not in rendered
    assert "href=\"app.css\"" not in rendered
    assert "document.body.dataset.ready" in rendered
    assert "<style>body {color: black}</style>" in rendered
    assert "data:image/svg+xml;base64," in rendered


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
    assert "<h1>Draft</h1>" in response.text
    assert "promethea:connect" in response.text
    assert response.headers["content-security-policy"].startswith("sandbox ")

    rejected = client.post("/canvas/ws1/env1/preview/", content="not allowed")
    assert rejected.status_code == 405
