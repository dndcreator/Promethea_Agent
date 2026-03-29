from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gateway.http import dispatcher
from gateway.protocol import RequestType


@pytest.mark.asyncio
async def test_dispatcher_error_model_uses_error_detail(monkeypatch):
    async def _fake_handle_http_request(**kwargs):
        _ = kwargs
        return SimpleNamespace(
            ok=False,
            error="Memory service not initialized",
            payload={
                "error_detail": {
                    "code": "service_unavailable",
                    "retryable": True,
                    "dependency": "memory_service",
                    "advice": "check memory initialization",
                    "trace_id": "trace_1",
                }
            },
        )

    fake_gateway = SimpleNamespace(handle_http_request=_fake_handle_http_request)
    monkeypatch.setattr(dispatcher, "get_gateway_server", lambda: fake_gateway)

    with pytest.raises(HTTPException) as exc:
        await dispatcher.dispatch_gateway_method(
            method=RequestType.MEMORY_QUERY,
            params={"query": "x"},
            user_id="u1",
        )

    detail = exc.value.detail
    assert detail["code"] == "service_unavailable"
    assert detail["retryable"] is True
    assert detail["dependency"] == "memory_service"
    assert detail["advice"] == "check memory initialization"
    assert detail["trace_id"] == "trace_1"


@pytest.mark.asyncio
async def test_dispatcher_error_model_infers_fields_from_plain_error(monkeypatch):
    async def _fake_handle_http_request(**kwargs):
        _ = kwargs
        return SimpleNamespace(ok=False, error="workflow engine not initialized", payload={})

    fake_gateway = SimpleNamespace(handle_http_request=_fake_handle_http_request)
    monkeypatch.setattr(dispatcher, "get_gateway_server", lambda: fake_gateway)

    with pytest.raises(HTTPException) as exc:
        await dispatcher.dispatch_gateway_method(
            method=RequestType.WORKFLOW_START,
            params={"workflow_id": "wf1"},
            user_id="u1",
        )

    detail = exc.value.detail
    assert detail["code"] == "service_unavailable"
    assert detail["dependency"] == "workflow_engine"
    assert detail["retryable"] is True
    assert "check workflow_engine initialization" in detail["advice"]
