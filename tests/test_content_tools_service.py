from __future__ import annotations

import os
import shutil

import pytest
from agentkit.security.http import HttpDocument

from agentkit.tools.content_tools.content_tools import ContentToolsService


@pytest.mark.asyncio
async def test_web_fetch_extracts_title_and_text(monkeypatch):
    svc = ContentToolsService()

    async def fake_request(url, **kwargs):
        html = "<html><head><title>Demo</title></head><body><h1>Hello</h1><a href='https://x.com'>x</a></body></html>"
        return HttpDocument(url, 200, "text/html", "utf-8", html.encode())

    monkeypatch.setattr("agentkit.tools.web_content.request_document", fake_request)

    out = await svc.web_fetch(url="https://example.com", include_links=True)
    assert out["ok"] is True
    assert out["title"] == "Demo"
    assert "Hello" in out["content"]
    assert out["links"]


def _make_workspace():
    from pathlib import Path

    base = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", ".tmp/pytest-runtime")) / "content-tools"
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
