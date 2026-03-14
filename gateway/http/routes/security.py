from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from gateway.security.audit import SecurityAuditService
from ..dispatcher import get_gateway_server
from .auth import get_current_user_id


router = APIRouter()


def _resolve_user_id(requested: Optional[str], current_user_id: str) -> str:
    if requested and requested != current_user_id:
        raise HTTPException(status_code=403, detail="cross-user security audit access is forbidden")
    return current_user_id


@router.get("/security/audit/report")
async def security_audit_report(
    user_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server = get_gateway_server()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)

    emitter = getattr(gateway_server, "event_emitter", None)
    if emitter is None:
        raise HTTPException(status_code=503, detail="event emitter unavailable")

    service = SecurityAuditService(emitter)
    report = service.build_report(user_id=resolved_user_id, limit=limit)
    return {"status": "success", "report": report}


@router.get("/security/audit/events")
async def security_audit_events(
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    gateway_server = get_gateway_server()
    resolved_user_id = _resolve_user_id(user_id, current_user_id)

    emitter = getattr(gateway_server, "event_emitter", None)
    if emitter is None:
        raise HTTPException(status_code=503, detail="event emitter unavailable")

    events = emitter.get_audit_history(user_id=resolved_user_id, action=action, limit=limit)
    rows = [event.model_dump() if hasattr(event, "model_dump") else dict(event) for event in events]
    return {
        "status": "success",
        "user_id": resolved_user_id,
        "action": action,
        "events": rows,
        "total": len(rows),
    }

