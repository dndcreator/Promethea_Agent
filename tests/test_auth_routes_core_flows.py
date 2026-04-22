from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi import Response
from jose import JWTError

from gateway.http.routes import auth
from gateway.http.schemas import APIConfigUpdate, UserConfigUpdate, UserDeleteRequest, UserLogin


@pytest.mark.asyncio
async def test_get_current_user_id_prefers_middleware_state():
    request = SimpleNamespace(state=SimpleNamespace(user_id="mw_user"))
    out = await auth.get_current_user_id(request=request, token=None)
    assert out == "mw_user"


@pytest.mark.asyncio
async def test_get_current_user_id_requires_token_without_middleware_user():
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as ei:
        await auth.get_current_user_id(request=request, token=None)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_extracts_sub_from_valid_token(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setattr(auth, "decode_access_token", lambda _: {"sub": "user_1"})
    out = await auth.get_current_user_id(request=request, token="tok")
    assert out == "user_1"


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_invalid_token(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace())

    def _boom(_: str):
        raise JWTError("bad token")

    monkeypatch.setattr(auth, "decode_access_token", _boom)
    with pytest.raises(HTTPException) as ei:
        await auth.get_current_user_id(request=request, token="bad")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_accepts_cookie_token(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace(), cookies={auth.AUTH_COOKIE_NAME: "cookie_tok"})
    monkeypatch.setattr(auth, "decode_access_token", lambda _: {"sub": "cookie_user"})
    out = await auth.get_current_user_id(request=request, token=None)
    assert out == "cookie_user"


@pytest.mark.asyncio
async def test_login_exposes_api_key_warning_when_global_key_missing(monkeypatch):
    monkeypatch.setattr(
        auth.user_manager,
        "verify_user",
        lambda username, password: {
            "user_id": "u1",
            "username": username,
            "agent_name": "Neo",
            "system_prompt": "base prompt",
        },
    )
    monkeypatch.setattr(auth.user_manager, "get_user_config", lambda _uid: {})
    monkeypatch.setattr(auth.config.api, "api_key", "placeholder-key-not-set", raising=False)

    response = Response()
    out = await auth.login(UserLogin(username="neo", password="pw"), response)
    assert out["token_type"] == "bearer"
    assert out["user_id"] == "u1"
    assert out["api_key_configured"] is False
    assert "Please set API__API_KEY" in out["warning"]
    assert out["access_token"]
    assert auth.AUTH_COOKIE_NAME in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_logout_clears_auth_cookie():
    response = Response()
    out = await auth.logout(response)
    assert out["status"] == "success"
    assert auth.AUTH_COOKIE_NAME in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_update_config_uses_config_service_and_scrubs_api_key(monkeypatch):
    config_service = MagicMock()
    config_service.update_user_config = AsyncMock(
        return_value={
            "success": True,
            "message": "ok",
            "config": {
                "agent_name": "Updated",
                "api": {"api_key": "secret", "model": "gpt-test"},
            },
        }
    )
    monkeypatch.setattr(auth, "_get_config_service", lambda: config_service)

    out = await auth.update_config(
        req=UserConfigUpdate(
            agent_name="Updated",
            api=APIConfigUpdate(api_key="new-key", model="gpt-test"),
        ),
        user_id="u1",
    )
    assert out["status"] == "success"
    assert out["canonical_endpoint"] == "/api/config/update"
    assert out["config"]["api"]["api_key"] == ""
    config_service.update_user_config.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_config_falls_back_to_legacy_when_gateway_unavailable(monkeypatch):
    def _raise_503():
        raise HTTPException(status_code=503, detail="Config service not initialized")

    monkeypatch.setattr(auth, "_get_config_service", _raise_503)

    graph_update = MagicMock(return_value=True)
    file_update = MagicMock(return_value=True)
    monkeypatch.setattr(auth.user_manager, "update_user_config", graph_update)
    monkeypatch.setattr(auth.user_manager, "update_user_config_file", file_update)

    out = await auth.update_config(
        req=UserConfigUpdate(agent_name="A1", system_prompt="S1"),
        user_id="u1",
    )
    assert out["status"] == "success"
    assert out["graph_sync_ok"] is True
    assert "legacy fallback" in out["message"]
    graph_update.assert_called_once_with("u1", agent_name="A1", system_prompt="S1")
    file_update.assert_called_once()


@pytest.mark.asyncio
async def test_delete_user_account_rejects_when_confirm_is_false():
    with pytest.raises(HTTPException) as ei:
        await auth.delete_user_account(req=UserDeleteRequest(confirm=False), user_id="u1")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_user_account_clears_user_sessions_and_deletes_user(monkeypatch):
    import gateway.http.message_manager as mm

    fake_manager = MagicMock()
    fake_manager.get_all_sessions_info.return_value = {"u1::sA": {}, "sB": {}}
    monkeypatch.setattr(mm, "message_manager", fake_manager)
    monkeypatch.setattr(auth.user_manager, "delete_user", lambda _uid: True)

    out = await auth.delete_user_account(req=UserDeleteRequest(confirm=True), user_id="u1")
    assert out["status"] == "success"
    fake_manager.delete_session.assert_any_call("sA", user_id="u1")
    fake_manager.delete_session.assert_any_call("sB", user_id="u1")
