from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config_gateway_handler import ConfigGatewayHandler
from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer


CONNECTION = SimpleNamespace(identity=SimpleNamespace(device_id="authenticated-user"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "reload", "update", "reset", "switch_model", "diagnose"])
async def test_missing_config_service_preserves_error_envelope(method):
    handler = ConfigGatewayHandler(lambda: None)
    out = await getattr(handler, method)(CONNECTION, RequestMessage(id="r", method=RequestType.CONFIG_GET, params={}))
    assert out.id == "r" and out.ok is False
    assert out.error == "Config service not initialized"


@pytest.mark.asyncio
async def test_registered_handler_resolves_current_injected_service_and_identity():
    server = GatewayServer()
    request = RequestMessage(id="r", method=RequestType.CONFIG_GET, params={"user_id": "untrusted"})
    handler = server._handlers[RequestType.CONFIG_GET]
    assert (await handler(CONNECTION, request)).ok is False
    for value in ("first", "second"):
        server.config_service = SimpleNamespace(get_merged_config=Mock(return_value={"model": value}))
        out = await handler(CONNECTION, request)
        assert out.payload == {"model": value}
        server.config_service.get_merged_config.assert_called_once_with("authenticated-user")


@pytest.mark.asyncio
async def test_update_keeps_validation_hot_apply_and_failure_semantics():
    service = SimpleNamespace(update_user_config=AsyncMock(return_value={"success": True}),
                              reload_default_config=AsyncMock(return_value={"success": False, "message": "reload failed"}))
    handler = ConfigGatewayHandler(lambda: service)
    request = RequestMessage(id="r", method=RequestType.CONFIG_UPDATE,
                             params={"config": {"agent_name": "Agent"}, "options": {"hot_apply": True}})
    out = await handler.update(CONNECTION, request)
    assert out.ok is True
    assert out.payload["hot_apply"] == {"requested": True, "success": False, "message": "reload failed"}
    service.update_user_config.assert_awaited_once_with("authenticated-user", {"agent_name": "Agent"}, validate=True)
    service.reload_default_config.assert_awaited_once()
