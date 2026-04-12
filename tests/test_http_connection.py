import pytest

from gateway.http_connection import HttpConnection


@pytest.mark.asyncio
async def test_http_connection_shape_and_noop_senders():
    conn = HttpConnection("u1")
    assert conn.is_authenticated is True
    assert conn.identity.device_id == "u1"
    assert conn.metadata.get("transport") == "http"
    assert str(conn.connection_id).startswith("http_")

    assert await conn.send_event("e", {}) is None
    assert await conn.send_message("m") is None
    assert await conn.send_response("r") is None
