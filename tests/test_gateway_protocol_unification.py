from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.conversation_service import ConversationService
from gateway.event_types import ALL_EVENT_TYPES
from gateway.protocol import (
    ConversationRunInput,
    ConversationRunOutput,
    EventType,
    GatewayEvent,
    GatewayRequest,
    GatewayResponse,
    RequestMessage,
    RequestType,
)
from gateway.server import GatewayServer


def test_gateway_request_serialization():
    request = RequestMessage(
        id="r1",
        method=RequestType.CHAT,
        params={"message": "hello", "session_id": "s1", "trace_id": "t1"},
    )
    gateway_request = GatewayRequest.from_request(
        request=request,
        user_id="u1",
        session_id="s1",
        channel_id="web",
    )

    dumped = gateway_request.model_dump()
    assert dumped["request_id"] == "r1"
    assert dumped["trace_id"] == "t1"
    assert dumped["session_id"] == "s1"
    assert dumped["user_id"] == "u1"
    assert dumped["input_text"] == "hello"


def test_gateway_response_serialization_payload_shape():
    gateway_response = GatewayResponse(
        request_id="r1",
        trace_id="t1",
        session_id="s1",
        user_id="u1",
        response_text="ok",
        status="success",
    )

    payload = gateway_response.to_payload()
    assert payload["request_id"] == "r1"
    assert payload["trace_id"] == "t1"
    assert payload["response_text"] == "ok"
    assert payload["response"] == "ok"


def test_gateway_event_serialization():
    event = GatewayEvent(
        event_type="gateway.request.received",
        trace_id="t1",
        request_id="r1",
        session_id="s1",
        user_id="u1",
        source_module="gateway.server",
        payload={"k": "v"},
        severity="info",
        tags=["gateway", "request"],
    )

    dumped = event.model_dump()
    assert dumped["event_type"] == "gateway.request.received"
    assert dumped["trace_id"] == "t1"
    assert dumped["payload"]["k"] == "v"


@pytest.mark.asyncio
async def test_conversation_service_structured_io_roundtrip():
    conversation_core = MagicMock()
    conversation_core.run_chat_loop = AsyncMock(return_value={"status": "success", "content": "done"})

    service = ConversationService(
        conversation_core=conversation_core,
        event_emitter=None,
    )
    run_input = ConversationRunInput(
        messages=[{"role": "user", "content": "hello"}],
        user_config={},
        session_id="s1",
        user_id="u1",
    )

    out = await service.run_conversation(run_input)

    assert isinstance(out, ConversationRunOutput)
    assert out.status == "success"
    assert out.content == "done"


@pytest.mark.asyncio
async def test_server_chat_uses_gateway_response_payload_shape():
    server = GatewayServer()

    message_manager = MagicMock()
    message_manager.get_session.return_value = True
    message_manager.begin_turn.return_value = True
    message_manager.commit_turn.return_value = True
    server.message_manager = message_manager

    conversation_service = MagicMock()
    conversation_service.prepare_chat_turn = AsyncMock(
        return_value={
            "messages": [{"role": "user", "content": "hello"}],
            "user_config": {},
            "reasoning": {},
        }
    )
    conversation_service.run_conversation = AsyncMock(
        return_value=ConversationRunOutput(status="success", content="ok", raw={"status": "success", "content": "ok"})
    )
    server.conversation_service = conversation_service
    server.reasoning_service = None

    connection = SimpleNamespace(
        connection_id="c1",
        identity=SimpleNamespace(device_id="u1"),
    )
    request = RequestMessage(
        id="r1",
        method=RequestType.CHAT,
        params={"message": "hello", "session_id": "s1", "trace_id": "t1", "user_id": "u1"},
    )

    response = await server._handle_chat(connection, request)

    assert response.ok is True
    assert response.payload["request_id"] == "r1"
    assert response.payload["trace_id"] == "t1"
    assert response.payload["session_id"] == "s1"
    assert response.payload["response_text"] == "ok"
    assert response.payload["response"] == "ok"


def test_canonical_gateway_event_types_centralized():
    assert "gateway.request.received" in ALL_EVENT_TYPES
    assert "gateway.run.finished" in ALL_EVENT_TYPES


@pytest.mark.asyncio
async def test_server_chat_emits_canonical_gateway_events():
    server = GatewayServer()
    server.event_emitter = MagicMock()
    server.event_emitter.emit = AsyncMock()

    message_manager = MagicMock()
    message_manager.get_session.return_value = True
    message_manager.begin_turn.return_value = True
    message_manager.commit_turn.return_value = True
    server.message_manager = message_manager

    conversation_service = MagicMock()
    conversation_service.prepare_chat_turn = AsyncMock(
        return_value={
            "messages": [{"role": "user", "content": "hello"}],
            "user_config": {},
            "reasoning": {},
        }
    )
    conversation_service.run_conversation = AsyncMock(
        return_value=ConversationRunOutput(
            status="success",
            content="ok",
            raw={"status": "success", "content": "ok"},
        )
    )
    server.conversation_service = conversation_service
    server.reasoning_service = None

    connection = SimpleNamespace(
        connection_id="c1",
        identity=SimpleNamespace(device_id="u1"),
    )
    request = RequestMessage(
        id="r1",
        method=RequestType.CHAT,
        params={"message": "hello", "session_id": "s1", "trace_id": "t1", "user_id": "u1"},
    )

    response = await server._handle_chat(connection, request)
    assert response.ok is True

    emitted_events = [call.args[0] for call in server.event_emitter.emit.await_args_list]
    assert EventType.GATEWAY_RUN_STARTED in emitted_events
    assert EventType.CONVERSATION_RUN_STARTED in emitted_events
    assert EventType.RESPONSE_SYNTHESIZED in emitted_events
    assert EventType.GATEWAY_RUN_FINISHED in emitted_events


@pytest.mark.asyncio
async def test_tool_service_mirrors_canonical_tool_events():
    from gateway.tool_service import ToolInvocationContext, ToolService

    event_emitter = MagicMock()
    event_emitter.emit = AsyncMock()
    service = ToolService(event_emitter=event_emitter, mcp_manager=MagicMock())

    class _LocalTool:
        tool_id = "local.echo"
        name = "Echo"
        description = "echo"

        async def invoke(self, args, ctx=None):
            return {"ok": True}

    service.register_tool(_LocalTool())

    await service.call_tool(
        "local.echo",
        {"x": 1},
        ctx=ToolInvocationContext(session_id="s1", user_id="u1", source="chat"),
        request_id="r1",
    )

    emitted_events = [call.args[0] for call in event_emitter.emit.await_args_list]
    assert EventType.TOOL_CALL_START in emitted_events
    assert EventType.TOOL_CALL_RESULT in emitted_events
    assert EventType.TOOL_EXECUTION_STARTED in emitted_events
    assert EventType.TOOL_EXECUTION_FINISHED in emitted_events
