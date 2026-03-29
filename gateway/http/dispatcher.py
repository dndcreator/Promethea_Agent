from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

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


def _error_code_from_error(error: str | None) -> str:
    msg = (error or "").lower()
    if "not found" in msg:
        return "not_found"
    if "forbidden" in msg:
        return "forbidden"
    if "unauthorized" in msg:
        return "unauthorized"
    if "not initialized" in msg:
        return "service_unavailable"
    if "not enabled" in msg:
        return "feature_disabled"
    if "timeout" in msg:
        return "timeout"
    if "invalid" in msg:
        return "invalid_request"
    return "gateway_error"


def _retryable_from_code(code: str) -> bool:
    return code in {"service_unavailable", "timeout"}


def _dependency_from_error(error: str | None) -> str:
    msg = (error or "").lower()
    if "memory" in msg:
        return "memory_service"
    if "workflow" in msg:
        return "workflow_engine"
    if "tool" in msg:
        return "tool_service"
    if "mcp" in msg:
        return "mcp_manager"
    if "config" in msg:
        return "config_service"
    if "workspace" in msg:
        return "workspace_service"
    return ""


def _advice_for_error(code: str, dependency: str) -> str:
    if code == "service_unavailable" and dependency:
        return f"check {dependency} initialization and runtime dependencies"
    if code == "feature_disabled":
        return "enable the feature in user/system configuration"
    if code == "timeout":
        return "retry request or increase timeout"
    if code in {"forbidden", "unauthorized"}:
        return "verify user/session ownership and policy permissions"
    if code == "invalid_request":
        return "validate request parameters and required fields"
    return "check logs and gateway status endpoints for diagnostics"


def _extract_error_detail(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    details = payload.get("error_detail")
    return details if isinstance(details, dict) else {}


async def dispatch_gateway_method(
    method: RequestType,
    params: Dict[str, Any],
    user_id: str,
    timeout_ms: Optional[int] = None,
    retries: int = 0,
    request: Optional[Request] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    merged_params = dict(params or {})
    key = idempotency_key or merged_params.pop("idempotency_key", None)
    if not key and request is not None:
        key = (
            request.headers.get("X-Idempotency-Key")
            or request.headers.get("Idempotency-Key")
        )
    gateway_server = get_gateway_server()
    response = await gateway_server.handle_http_request(
        method=method,
        params=merged_params,
        user_id=user_id,
        timeout_ms=timeout_ms,
        retries=retries,
        idempotency_key=key,
    )

    if not response.ok:
        message = response.error or "Gateway request failed"
        detail = _extract_error_detail(response.payload)
        code = str(detail.get("code") or _error_code_from_error(message))
        dependency = str(detail.get("dependency") or _dependency_from_error(message))
        retryable = bool(detail.get("retryable")) if "retryable" in detail else _retryable_from_code(code)
        advice = str(detail.get("advice") or _advice_for_error(code, dependency))
        trace_id = str(detail.get("trace_id") or (response.payload or {}).get("trace_id") or "")
        raise HTTPException(
            status_code=_http_status_from_error(message),
            detail={
                "code": code,
                "message": message,
                "retryable": retryable,
                "dependency": dependency,
                "advice": advice,
                "trace_id": trace_id,
            },
        )
    return response.payload or {}

