import json
import mimetypes
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

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


@router.get("/artifact")
async def get_workbench_artifact(
    workspace_id: str,
    path: str,
    user_id: str = Depends(get_current_user_id),
):
    workspace_service = getattr(get_gateway_server(), "workspace_service", None)
    if workspace_service is None:
        raise HTTPException(status_code=503, detail="Workspace service not initialized")
    handle = workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
    root = Path(handle.root_path).resolve()
    target = (root / str(path or "")).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Artifact path escapes workspace") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    active_document = media_type in {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if active_document:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return FileResponse(
        target,
        filename=target.name,
        media_type=media_type,
        content_disposition_type="attachment" if active_document else "inline",
        headers=headers,
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
        ambient_version = None
        while not await request.is_disconnected():
            snapshot = _snapshot(
                projection=projection, user_id=user_id, task_id=task_id, run_id=run_id,
                session_id=session_id, after_seq=0, limit=limit,
            )
            timeline = snapshot.get("timeline") or []
            next_cursor = max(cursor, int(snapshot.get("cursor") or 0))
            version = json.dumps(snapshot.get("ambient"), sort_keys=True)
            if first or next_cursor > cursor or version != ambient_version:
                ambient_version = version
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
                timeout=3.0 if (snapshot.get("ambient") or {}).get("settings", {}).get("enabled") else 15.0,
            )
            if not changed:
                yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
