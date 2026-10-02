from __future__ import annotations

from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

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
            "memory_write_summary": {
                "enabled": True,
                "write_notice": "saved",
                "notices": ["saved"],
                "feedback_hints": [{"type": "memory_saved"}],
            },
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
    assert isinstance(out.memory_write_summary, dict)
    assert out.memory_write_summary.get("enabled") is True


@pytest.mark.asyncio
async def test_chat_route_passes_attachments_without_prompt_merging(monkeypatch):
    captured = {}

    async def _fake_dispatch(method, payload, user_id=None, request=None):
        _ = (method, user_id, request)
        captured.update(payload)
        return {"response": "ok", "session_id": "s1", "status": "success"}

    monkeypatch.setattr(
        chat_routes,
        "get_gateway_server",
        lambda: SimpleNamespace(channel_adapter_registry=None),
    )
    monkeypatch.setattr(chat_routes, "dispatch_gateway_method", _fake_dispatch)
    out = await chat_routes.chat(
        request=chat_routes.ChatRequest(
            message="summarize this",
            stream=False,
            requested_mode="deep",
            requested_skill="research",
            requested_workflow="source-review",
            metadata={"origin": "sdk-test"},
            attachments=[{"file_id": "f1"}],
        ),
        raw_request=SimpleNamespace(),
        user_id="u1",
    )

    assert out.status == "success"
    assert captured["attachments"] == [{"file_id": "f1"}]
    assert captured["message"] == "summarize this"
    assert captured["requested_mode"] == "deep"
    assert captured["requested_skill"] == "research"
    assert captured["requested_workflow"] == "source-review"
    assert captured["metadata"] == {"origin": "sdk-test"}


@pytest.mark.asyncio
async def test_chat_route_keeps_image_attachment_as_structured_input(monkeypatch):
    captured = {}

    async def _fake_dispatch(method, payload, user_id=None, request=None):
        _ = (method, user_id, request)
        captured.update(payload)
        return {"response": "ok", "session_id": "s1", "status": "success"}

    monkeypatch.setattr(
        chat_routes,
        "get_gateway_server",
        lambda: SimpleNamespace(channel_adapter_registry=None),
    )
    monkeypatch.setattr(chat_routes, "dispatch_gateway_method", _fake_dispatch)
    await chat_routes.chat(
        request=chat_routes.ChatRequest(
            message="what is in the image?",
            stream=False,
            attachments=[{"file_id": "img1"}],
        ),
        raw_request=SimpleNamespace(),
        user_id="u1",
    )

    assert captured["message"] == "what is in the image?"
    assert captured["attachments"] == [{"file_id": "img1"}]


@pytest.mark.asyncio
async def test_streaming_chat_uses_tool_loop_when_prompt_policy_needs_tools(monkeypatch):
    class _MessageManager:
        def get_session(self, session_id, user_id=None):
            _ = (session_id, user_id)
            return True

        def begin_turn(self, **kwargs):
            _ = kwargs
            return True

        def commit_turn(self, **kwargs):
            _ = kwargs
            return True

        def abort_turn(self, *args, **kwargs):
            _ = (args, kwargs)

        def get_recent_messages(self, *args, **kwargs):
            _ = (args, kwargs)
            return []

    class _ConversationService:
        def __init__(self):
            self.stream_called = False
            self.run_called = False
            self.run_kwargs = {}

        async def prepare_chat_turn(self, **kwargs):
            _ = kwargs
            return {
                "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "calc"}],
                "user_config": {},
                "reasoning": {},
                "prompt_policy": {"need_tools": True, "tool_budget": 2},
                "execution_budget": {"tool_budget": 2},
            }

        async def call_llm_stream(self, *args, **kwargs):
            self.stream_called = True
            _ = (args, kwargs)
            yield '{"action":"tool_call","tool_name":"calculator.calculate",'
            yield '"args":{"expression":"2 + 2"}}'

        async def run_chat_loop(self, *args, **kwargs):
            self.run_called = True
            self.run_kwargs = dict(kwargs)
            _ = args
            return {"status": "success", "content": "tool-backed answer"}

    conversation_service = _ConversationService()
    captured_context = {}

    def _build_run_context(**kwargs):
        captured_context.update(kwargs["input_payload"])
        return SimpleNamespace(
            trace_id="trace-stream",
            input_payload=dict(kwargs["input_payload"]),
            requested_mode=kwargs["input_payload"].get("requested_mode"),
            requested_skill=kwargs["input_payload"].get("requested_skill"),
            requested_workflow=kwargs["input_payload"].get("requested_workflow"),
        )

    gateway_server = SimpleNamespace(
        message_manager=_MessageManager(),
        conversation_service=conversation_service,
        reasoning_service=None,
        event_emitter=None,
        config_service=None,
        _build_run_context=_build_run_context,
        _apply_skill_runtime_context=lambda **kwargs: None,
        _execute_tool_for_chat=AsyncMock(return_value={"ok": True}),
    )
    monkeypatch.setattr(chat_routes, "get_gateway_server", lambda: gateway_server)

    response = await chat_routes.chat(
        request=chat_routes.ChatRequest(
            message="please calculate with tool",
            stream=True,
            session_id="s1",
            requested_mode="deep",
            requested_skill="calculator",
            requested_workflow="analysis",
            metadata={"origin": "sdk-test"},
        ),
        raw_request=SimpleNamespace(),
        user_id="u1",
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
    payload = "".join(chunks)

    assert conversation_service.run_called is True
    assert conversation_service.stream_called is True
    assert conversation_service.run_kwargs.get("max_recursion") == 2
    assert conversation_service.run_kwargs.get("initial_response") == {
        "content": '{"action":"tool_call","tool_name":"calculator.calculate",'
        '"args":{"expression":"2 + 2"}}'
    }
    assert conversation_service.run_kwargs.get("run_context").requested_mode == "deep"
    assert captured_context["requested_skill"] == "calculator"
    assert captured_context["requested_workflow"] == "analysis"
    assert captured_context["metadata"] == {"origin": "sdk-test"}
    assert "id: http_stream_" in payload
    assert "event: session_started" in payload
    assert '"event_type": "session_started"' in payload
    assert '"type": "session_started"' in payload
    assert "tool_meta" in payload
    assert "tool-backed answer" in payload


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
            "memory_write_summary": {
                "enabled": True,
                "review_notice": "needs review",
                "feedback_hints": [{"type": "memory_review_needed"}],
            },
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
    assert out.memory_write_summary.get("enabled") is True


def test_stream_prefix_classifier_only_buffers_runtime_envelopes():
    assert chat_routes._is_incomplete_routing_envelope('  {"action"') is True
    assert chat_routes._is_incomplete_routing_envelope('{"tool_name":"web.search"') is True
    assert chat_routes._is_incomplete_routing_envelope('```json\n{"action":"tool_call"') is True
    assert chat_routes._is_incomplete_routing_envelope('```python\nprint("hello")') is False
    assert chat_routes._is_incomplete_routing_envelope('{"result": 42') is False
    assert chat_routes._is_incomplete_routing_envelope('Normal streamed answer') is False
