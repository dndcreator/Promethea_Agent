from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...avatar_service import avatar_service
from .auth import get_current_user_id


router = APIRouter()


class AvatarEnabledRequest(BaseModel):
    enabled: bool


@router.get("/avatar/current")
async def get_current_avatar(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    return {"status": "success", "avatar": avatar_service.get_current(user_id=user_id)}


@router.post("/avatar/upload")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    raw = await file.read()
    avatar = avatar_service.save_upload(
        user_id=user_id,
        filename=str(getattr(file, "filename", "") or ""),
        content=raw,
        content_type=str(getattr(file, "content_type", "") or ""),
    )
    return {"status": "success", "avatar": avatar}


@router.put("/avatar/current")
async def update_current_avatar(
    request: AvatarEnabledRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return {"status": "success", "avatar": avatar_service.set_enabled(user_id=user_id, enabled=request.enabled)}


@router.delete("/avatar/current")
async def clear_current_avatar(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    return {"status": "success", "avatar": avatar_service.clear(user_id=user_id)}


@router.get("/avatar/assets/{avatar_id}")
async def get_avatar_asset(
    avatar_id: str,
    user_id: str = Depends(get_current_user_id),
):
    path = avatar_service.get_asset_path(user_id=user_id, avatar_id=avatar_id)
    if not path:
        raise HTTPException(status_code=404, detail="avatar asset not found")
    manifest = avatar_service.get_current(user_id=user_id)
    return FileResponse(
        path=str(path),
        media_type=str(manifest.get("content_type") or "application/octet-stream"),
        filename=str(manifest.get("filename") or path.name),
    )
