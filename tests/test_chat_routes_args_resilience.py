from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.http.routes import chat as chat_routes


@pytest.mark.asyncio
async def test_chat_route_normalizes_non_dict_args(monkeypatch):
    async def _fake_dispatch(method, payload, user_id=None, request=None):
        _ = (method, payload, user_id, request)
        return {
            "response": "ok",
            "session_id": "s1",
            "status": "needs_confirmation",
            "tool_call_id": "tc1",
            "tool_name": "execute_command",
            "args": ("command", "description", "service_name", "agentType"),
        }

    monkeypatch.setattr(
        chat_routes,
        "get_gateway_server",
        lambda: SimpleNamespace(channel_adapter_registry=None),
    )
    monkeypatch.setattr(chat_routes, "dispatch_gateway_method", _fake_dispatch)

    out = await chat_routes.chat(
        request=chat_routes.ChatRequest(message="open cmd", stream=False),
        raw_request=SimpleNamespace(),
        user_id="u1",
    )

    assert out.status == "needs_confirmation"
    assert isinstance(out.args, dict)
    assert out.args == {"_args_list": ["command", "description", "service_name", "agentType"]}


@pytest.mark.asyncio
async def test_chat_confirm_route_normalizes_non_dict_args(monkeypatch):
    async def _fake_dispatch(method, payload, user_id=None, request=None):
        _ = (method, payload, user_id, request)
        return {
            "response": "ok",
            "session_id": "s1",
            "status": "needs_confirmation",
            "tool_call_id": "tc1",
            "tool_name": "execute_command",
            "args": ("command", "description"),
        }

    monkeypatch.setattr(chat_routes, "dispatch_gateway_method", _fake_dispatch)

    out = await chat_routes.confirm_tool(
        request=chat_routes.ConfirmToolRequest(
            session_id="s1",
            tool_call_id="tc1",
            action="approve",
        ),
        raw_request=SimpleNamespace(),
        user_id="u1",
    )

    assert out.status == "needs_confirmation"
    assert out.args == {"_args_list": ["command", "description"]}
