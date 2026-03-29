from types import SimpleNamespace

import pytest

from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer
from gateway.tool_service import ToolService


class _EchoTool:
    tool_id = "local.echo"
    name = "Echo"
    description = "Echo"

    async def invoke(self, args, ctx=None):
        _ = (args, ctx)
        return {"ok": True}


@pytest.mark.asyncio
async def test_gateway_tools_list_includes_catalog_callable_fields():
    server = GatewayServer()
    service = ToolService(event_emitter=server.event_emitter)
    service.register_tool(_EchoTool())
    server.tool_service = service
    connection = SimpleNamespace(connection_id="c1", identity=SimpleNamespace(device_id="u1"))
    req = RequestMessage(id="r1", method=RequestType.TOOLS_LIST, params={"user_id": "u1"})

    res = await server._handle_tools_list(connection, req)
    assert res.ok is True
    payload = res.payload or {}
    assert "catalog" in payload
    assert "catalog_callable_now" in payload
    assert payload["catalog_callable_now"] >= 1
