from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from gateway.protocol import RequestType
from gateway_integration import get_gateway_integration


def get_gateway_server():
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server:
        raise HTTPException(status_code=503, detail="Gateway server not initialized")
    return gateway_server


def _http_status_from_error(error: str | None) -> int:
    msg = (error or "").lower()
    if "not found" in msg:
        return 404
    if "forbidden" in msg or "unauthorized" in msg:
        return 403
    if "not initialized" in msg or "not enabled" in msg:
        return 503
    if "timeout" in msg:
        return 504
    return 400


async def dispatch_gateway_method(
    method: RequestType,
    params: Dict[str, Any],
    user_id: str,
    timeout_ms: Optional[int] = None,
    retries: int = 0,
) -> Dict[str, Any]:
    gateway_server = get_gateway_server()
    response = await gateway_server.handle_http_request(
        method=method,
        params=params or {},
        user_id=user_id,
        timeout_ms=timeout_ms,
        retries=retries,
    )

    if not response.ok:
        raise HTTPException(
            status_code=_http_status_from_error(response.error),
            detail=response.error or "Gateway request failed",
        )
    return response.payload or {}

