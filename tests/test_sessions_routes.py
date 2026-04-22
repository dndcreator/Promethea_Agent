from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gateway.http.routes import sessions


@pytest.mark.asyncio
async def test_sessions_list_passes_query_params(monkeypatch):
    captured = {}

    async def _fake_dispatch(method, params, user_id):
        captured["method"] = method
        captured["params"] = dict(params or {})
        captured["user_id"] = user_id
        return {"sessions": [], "total": 0}

    monkeypatch.setattr(sessions, "dispatch_gateway_method", _fake_dispatch)
    out = await sessions.list_sessions(q="roadmap", pinned_only=True, limit=15, user_id="u1")
    assert out["status"] == "success"
    assert captured["params"]["q"] == "roadmap"
    assert captured["params"]["pinned_only"] is True
    assert captured["params"]["limit"] == 15


@pytest.mark.asyncio
async def test_session_pin_success(monkeypatch):
    class _MM:
        def set_session_pinned(self, *, session_id, user_id, pinned):
            return session_id == "s1" and user_id == "u1" and pinned is True

    monkeypatch.setattr(
        sessions,
        "get_gateway_server",
        lambda: SimpleNamespace(message_manager=_MM()),
    )

    out = await sessions.set_session_pin("s1", sessions.SessionPinRequest(pinned=True), user_id="u1")
    assert out["status"] == "success"
    assert out["pinned"] is True


@pytest.mark.asyncio
async def test_session_pin_not_found(monkeypatch):
    class _MM:
        def set_session_pinned(self, *, session_id, user_id, pinned):
            _ = (session_id, user_id, pinned)
            return False

    monkeypatch.setattr(
        sessions,
        "get_gateway_server",
        lambda: SimpleNamespace(message_manager=_MM()),
    )

    with pytest.raises(HTTPException) as ei:
        await sessions.set_session_pin("missing", sessions.SessionPinRequest(pinned=True), user_id="u1")
    assert ei.value.status_code == 404
