import pytest

from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer


class _DummyConnection:
    def __init__(self) -> None:
        self.connection_id = "conn_test"
        self.messages = []

    async def send_message(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_ws_request_invalid_params_includes_structured_error_detail():
    server = GatewayServer()
    conn = _DummyConnection()
    req = RequestMessage(id="req_1", method=RequestType.MEMORY_GRAPH, params={})

    await server._handle_request(conn, req)

    assert len(conn.messages) == 1
    response = conn.messages[0]
    assert response.ok is False
    assert response.payload and "error_detail" in response.payload
    detail = response.payload["error_detail"]
    assert detail["code"] == "invalid_request"
    assert detail["trace_id"] == "trace_req_1"


@pytest.mark.asyncio
async def test_ws_request_service_guard_includes_service_unavailable_error_detail():
    server = GatewayServer()
    conn = _DummyConnection()
    req = RequestMessage(id="req_2", method=RequestType.WORKFLOW_START, params={})

    await server._handle_request(conn, req)

    assert len(conn.messages) == 1
    response = conn.messages[0]
    assert response.ok is False
    assert response.payload and "error_detail" in response.payload
    detail = response.payload["error_detail"]
    assert detail["code"] == "service_unavailable"
    assert detail["dependency"] == "workflow_engine"
