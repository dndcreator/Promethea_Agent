from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.models import RunContext, SessionState
from gateway.protocol import ConversationRunOutput, RequestMessage, RequestType
from gateway.server import GatewayServer


def test_session_state_defaults_and_dump():
    state = SessionState(session_id="s1", user_id="u1", trace_id="t1")
    dumped = state.model_dump()

    assert dumped["session_id"] == "s1"
    assert dumped["user_id"] == "u1"
    assert dumped["trace_id"] == "t1"
    assert dumped["status"] == "active"


def test_run_context_properties():
    state = SessionState(session_id="s1", user_id="u1", trace_id="t1")
    ctx = RunContext(request_id="r1", trace_id="t1", session_state=state)

    assert ctx.session_id == "s1"
    assert ctx.user_id == "u1"
    assert ctx.trace_id == "t1"


@pytest.mark.asyncio
async def test_gateway_chat_builds_and_passes_run_context():
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
    assert response.payload["trace_id"] == "t1"
    assert response.payload["session_id"] == "s1"

    prep_kwargs = conversation_service.prepare_chat_turn.await_args.kwargs
    run_ctx = prep_kwargs["run_context"]
    assert isinstance(run_ctx, RunContext)
    assert run_ctx.trace_id == "t1"
    run_input = conversation_service.run_conversation.await_args.args[0]
    assert run_input.run_context.trace_id == "t1"


