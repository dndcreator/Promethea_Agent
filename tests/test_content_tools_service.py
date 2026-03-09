from __future__ import annotations

import shutil

import pytest

from agentkit.tools.content_tools.content_tools import ContentToolsService


class _FakeResp:
    def __init__(self, body: str, status: int = 200, content_type: str = "text/html"):
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_web_fetch_extracts_title_and_text(monkeypatch):
    svc = ContentToolsService()

    def fake_urlopen(req, timeout=20):
        html = "<html><head><title>Demo</title></head><body><h1>Hello</h1><a href='https://x.com'>x</a></body></html>"
        return _FakeResp(html)

    monkeypatch.setattr("agentkit.tools.content_tools.content_tools.request.urlopen", fake_urlopen)

    out = await svc.web_fetch(url="https://example.com", include_links=True)
    assert out["ok"] is True
    assert out["title"] == "Demo"
    assert "Hello" in out["content"]
    assert out["links"]


def _make_workspace():
    from pathlib import Path

    base = Path(".pytest-content-tools")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


@pytest.mark.asyncio
async def test_image_action_metadata_requires_existing_file():
    ws = _make_workspace()
    svc = ContentToolsService(workspace_root=str(ws))
    with pytest.raises(FileNotFoundError):
        await svc.image_action(action="metadata", path="missing.png")

@pytest.mark.asyncio
async def test_web_fetch_blocked_by_sandbox(monkeypatch):
    svc = ContentToolsService()

    class _Policy:
        def check_url(self, url):
            class _D:
                allowed = False
                reason = "blocked"
            return _D()

    svc._sandbox = _Policy()
    with pytest.raises(PermissionError):
        await svc.web_fetch(url="https://example.com")
