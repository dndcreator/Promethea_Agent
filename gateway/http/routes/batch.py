from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from gateway.protocol import RequestType

from ..dispatcher import dispatch_gateway_method
from ..schemas import BatchRequest
from .auth import get_current_user_id


router = APIRouter()


@router.post("/batch")
async def batch_dispatch(
    request: BatchRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not request.requests:
        raise HTTPException(status_code=400, detail="requests is required")

    # Higher priority first.
    sorted_items = sorted(
        request.requests,
        key=lambda x: int(x.priority),
        reverse=True,
    )
    results = []
    for item in sorted_items:
        try:
            method = RequestType(item.method)
        except Exception:
            results.append(
                {
                    "method": item.method,
                    "ok": False,
                    "error": f"Unknown request method: {item.method}",
                }
            )
            continue

        try:
            payload = await dispatch_gateway_method(
                method=method,
                params=item.params or {},
                user_id=user_id,
                timeout_ms=item.timeout_ms,
                retries=item.retries,
            )
            results.append({"method": item.method, "ok": True, "payload": payload})
        except HTTPException as e:
            results.append({"method": item.method, "ok": False, "error": str(e.detail)})
        except Exception as e:
            logger.error("batch request failed: {}", e)
            results.append({"method": item.method, "ok": False, "error": str(e)})

    return {"status": "success", "results": results}

