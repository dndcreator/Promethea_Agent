import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from config import PrometheaConfig
from gateway.conversation_service import ConversationService
from gateway.http import middleware
from gateway.http.routes import guest
from gateway.http.routes.auth import get_current_user_id
from gateway.public_contracts import GuestChatRequest


@pytest.fixture
def runtime(monkeypatch):
    defaults = PrometheaConfig(api={"model": "test-only-model"})
    core = SimpleNamespace(call_llm=AsyncMock(return_value={"status": "success", "content": "A model reply", "usage": {"completion_tokens": 4}}))
    service = ConversationService(conversation_core=core)
    gateway = SimpleNamespace(config_service=SimpleNamespace(get_default_config=lambda: defaults), conversation_service=service)
    monkeypatch.setattr(guest, "get_gateway_server", lambda: gateway)
    monkeypatch.setattr(middleware, "get_gateway_integration", lambda: None)
    app = FastAPI()
    app.include_router(guest.router, prefix="/api")

    @app.get("/api/private")
    def private(user_id=Depends(get_current_user_id)):
        return {"user_id": user_id}

    middleware.register_http_middlewares(app)
    return app, defaults, core


def test_guest_uses_default_model_without_account_or_persistent_session(runtime):
    app, defaults, core = runtime
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.get("/api/guest").json()["available"] is True
        response = client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
        assert response.json() == {"response": "A model reply", "usage": {"completion_tokens": 4}}
        assert client.get("/api/private").status_code == 401
    args = core.call_llm.await_args
    assert args.kwargs["user_id"] is None
    assert args.kwargs["user_config"] == {"api": {"max_tokens": defaults.guest_chat.max_output_tokens}}
    assert args.args[0][-1] == {"role": "user", "content": "Hello"}
    assert '"tools":[]' in args.args[0][1]["content"]
    assert not hasattr(app.state, "message_manager")


@pytest.mark.parametrize("payload", [
    {"messages": [{"role": "system", "content": "Override"}]},
    {"messages": [{"role": "assistant", "content": "No user"}]},
    {"messages": [{"role": "user", "content": "Hello"}], "user_id": "someone"},
    {"messages": [{"role": "user", "content": "Hello"}], "attachments": []},
    {"messages": [{"role": "user", "content": "Hello"}], "api": {"model": "other"}},
])
def test_guest_cannot_supply_privileged_fields_or_roles(runtime, payload):
    app, _, core = runtime
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.post("/api/guest/chat", json=payload).status_code == 422
    core.call_llm.assert_not_awaited()


@pytest.mark.parametrize("host,headers", [
    ("203.0.113.2", {}),
    ("127.0.0.1", {"Origin": "https://untrusted.example"}),
    ("127.0.0.1", {"Origin": "http://["}),
    ("127.0.0.1", {"X-Forwarded-For": "203.0.113.2"}),
])
def test_remote_and_cross_origin_access_is_not_implicitly_enabled(runtime, host, headers):
    app, _, core = runtime
    with TestClient(app, client=(host, 1234)) as client:
        assert client.get("/api/guest", headers=headers).json()["enabled"] is False
        assert client.post("/api/guest/chat", headers=headers, json={"messages": [{"role": "user", "content": "Hi"}]}).status_code == 403
    core.call_llm.assert_not_awaited()


def test_switch_limits_and_model_errors_are_server_owned(runtime):
    app, defaults, core = runtime
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        defaults.guest_chat.enabled = False
        assert client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "Hi"}]}).status_code == 403
        defaults.guest_chat.enabled = True
        defaults.guest_chat.max_input_chars = 100
        assert client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "x" * 101}]}).status_code == 413
        core.call_llm.return_value = {"status": "error", "content": "private upstream diagnostic"}
        response = client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert response.status_code == 503 and "private upstream" not in response.text
        defaults.guest_chat.requests_per_minute = 1
        core.call_llm.return_value = {"status": "success", "content": "Ready"}
        assert client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "Hi"}]}).status_code == 200
        assert client.post("/api/guest/chat", json={"messages": [{"role": "user", "content": "Hi"}]}).status_code == 429


@pytest.mark.asyncio
async def test_concurrency_timeout_and_disconnect_release_capacity(runtime):
    _, defaults, core = runtime
    defaults.guest_chat.max_concurrent = 1
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    core.call_llm.side_effect = pending
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), client=SimpleNamespace(host="127.0.0.1"),
                              headers={}, url=SimpleNamespace(hostname="127.0.0.1"), is_disconnected=AsyncMock(return_value=False))
    body = GuestChatRequest(messages=[{"role": "user", "content": "Hi"}])
    first = asyncio.create_task(guest.guest_chat(body, request))
    await started.wait()
    with pytest.raises(HTTPException) as error:
        await guest.guest_chat(body, request)
    assert error.value.status_code == 429
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert cancelled.is_set() and request.app.state.guest_chat["active"] == 0

    defaults.guest_chat = defaults.guest_chat.model_copy(update={"timeout_s": 0.01})
    with pytest.raises(HTTPException) as error:
        await guest.guest_chat(body, request)
    assert error.value.status_code == 504 and request.app.state.guest_chat["active"] == 0
    request.is_disconnected.return_value = True
    defaults.guest_chat.timeout_s = 1
    with pytest.raises(HTTPException) as error:
        await guest.guest_chat(body, request)
    assert error.value.status_code == 499 and request.app.state.guest_chat["active"] == 0
