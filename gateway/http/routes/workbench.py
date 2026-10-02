import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from gateway.public_contracts import WorkbenchSnapshot
from gateway.public_views import public_workbench

from ..dispatcher import get_gateway_server
from .auth import get_current_user_id


router = APIRouter(prefix="/workbench", tags=["workbench"])


def _projection():
    projection = getattr(get_gateway_server(), "workbench_projection", None)
    if projection is None:
        raise HTTPException(status_code=503, detail="Workbench projection not initialized")
    return projection


def _snapshot(*, projection, user_id: str, task_id: Optional[str], run_id: Optional[str], session_id: Optional[str], after_seq: int, limit: int):
    return public_workbench(projection.snapshot(
        user_id=user_id,
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        after_seq=after_seq,
        limit=limit,
    ))


@router.get("/snapshot", response_model=WorkbenchSnapshot)
async def get_workbench_snapshot(
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    after_seq: int = 0,
    limit: int = 120,
    user_id: str = Depends(get_current_user_id),
):
    return _snapshot(
        projection=_projection(), user_id=user_id, task_id=task_id, run_id=run_id,
        session_id=session_id, after_seq=after_seq, limit=limit,
    )


@router.get("/stream")
async def stream_workbench(
    request: Request,
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    after_seq: int = 0,
    limit: int = 160,
    user_id: str = Depends(get_current_user_id),
):
    projection = _projection()

    async def events() -> AsyncIterator[str]:
        cursor = max(0, int(after_seq or 0))
        first = True
        while not await request.is_disconnected():
            snapshot = _snapshot(
                projection=projection, user_id=user_id, task_id=task_id, run_id=run_id,
                session_id=session_id, after_seq=cursor, limit=limit,
            )
            timeline = snapshot.get("timeline") or []
            next_cursor = max(cursor, int(snapshot.get("cursor") or 0))
            if first or timeline:
                cursor = next_cursor
                body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {cursor}\nevent: snapshot\ndata: {body}\n\n"
                first = False
                continue
            cursor = next_cursor
            changed = await projection.wait_for_change(
                user_id=user_id,
                after_seq=cursor,
                task_id=task_id,
                run_id=run_id,
                session_id=session_id,
                timeout=15.0,
            )
            if not changed:
                yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
