from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gateway.http.routes import search


@pytest.mark.asyncio
async def test_unified_search_combines_sessions_and_files(monkeypatch):
    class _MM:
        def list_sessions(self, *, user_id, query, pinned_only, limit):
            _ = (pinned_only, limit)
            return [{"session_id": "s1", "title": f"hit:{query}", "user_id": user_id}]

    monkeypatch.setattr(
        search,
        "get_gateway_server",
        lambda: SimpleNamespace(message_manager=_MM()),
    )
    monkeypatch.setattr(
        search.user_file_store,
        "search_files",
        lambda **kwargs: [{"file_id": "f1", "filename": "notes.txt", "snippet": kwargs.get("query")}],
    )

    out = await search.unified_search(q="plan", user_id="u1")
    assert out["status"] == "success"
    assert out["totals"]["sessions"] == 1
    assert out["totals"]["files"] == 1


@pytest.mark.asyncio
async def test_unified_search_requires_query():
    with pytest.raises(HTTPException) as ei:
        await search.unified_search(q="", user_id="u1")
    assert ei.value.status_code == 400
