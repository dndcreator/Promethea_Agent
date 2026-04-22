from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from .auth import get_current_user_id
from ..user_file_store import user_file_store


router = APIRouter()


@router.post("/files/upload")
async def upload_user_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    raw = await file.read()
    entry = user_file_store.save_upload(
        user_id=user_id,
        filename=str(getattr(file, "filename", "") or ""),
        content=raw,
        content_type=str(getattr(file, "content_type", "") or ""),
        session_id=str(session_id or ""),
    )
    return {"status": "success", "file": entry}


@router.get("/files")
async def list_user_files(
    q: str = "",
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    if str(q or "").strip():
        files = user_file_store.search_files(user_id=user_id, query=q, limit=limit)
        return {"status": "success", "files": files, "total": len(files), "query": q}
    files = user_file_store.list_files(user_id=user_id, limit=limit)
    return {"status": "success", "files": files, "total": len(files)}
