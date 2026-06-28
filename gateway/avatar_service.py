from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


class AvatarService:
    """Store user avatar assets separately from searchable chat attachments."""

    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    VIDEO_SUFFIXES = {".webm", ".mp4"}

    def __init__(self, root_dir: str = "config/users", max_upload_bytes: int = 25 * 1024 * 1024) -> None:
        self.root_dir = Path(root_dir)
        self.max_upload_bytes = int(max_upload_bytes)

    def _avatar_root(self, user_id: str) -> Path:
        return self.root_dir / str(user_id) / "avatar"

    def _manifest_path(self, user_id: str) -> Path:
        return self._avatar_root(user_id) / "manifest.json"

    def _asset_dir(self, user_id: str) -> Path:
        return self._avatar_root(user_id) / "assets"

    def get_current(self, *, user_id: str) -> Dict[str, Any]:
        path = self._manifest_path(user_id)
        if not path.exists():
            return self._empty_manifest()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_manifest()
        if not isinstance(payload, dict):
            return self._empty_manifest()
        return {
            **self._empty_manifest(),
            **payload,
            "enabled": bool(payload.get("enabled", True)),
        }

    def save_upload(self, *, user_id: str, filename: str, content: bytes, content_type: str = "") -> Dict[str, Any]:
        raw_name = Path(str(filename or "").strip()).name
        if not raw_name:
            raise HTTPException(status_code=400, detail="filename is required")
        if not content:
            raise HTTPException(status_code=400, detail="empty avatar file")
        if len(content) > self.max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"avatar file too large (>{self.max_upload_bytes} bytes)")

        suffix = Path(raw_name).suffix.lower()
        kind = self._kind_for_suffix(suffix)
        if not kind:
            allowed = sorted(self.IMAGE_SUFFIXES | self.VIDEO_SUFFIXES)
            raise HTTPException(status_code=400, detail=f"unsupported avatar type: {suffix or 'unknown'}; allowed: {', '.join(allowed)}")

        previous = self.get_current(user_id=user_id)
        avatar_id = f"avatar_{uuid.uuid4().hex}"
        stored_name = f"{avatar_id}{suffix}"
        asset_path = self._asset_dir(user_id) / stored_name
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(content)

        manifest = {
            "avatar_id": avatar_id,
            "enabled": True,
            "kind": kind,
            "filename": raw_name,
            "stored_name": stored_name,
            "content_type": str(content_type or self._default_content_type(suffix)),
            "bytes": len(content),
            "updated_at": int(time.time()),
            "asset_url": f"/api/avatar/assets/{avatar_id}",
            "driver": kind,
            "capabilities": ["display"],
        }
        _atomic_write_json(self._manifest_path(user_id), manifest)
        self._remove_previous_asset(user_id=user_id, previous=previous, keep=stored_name)
        return manifest

    def set_enabled(self, *, user_id: str, enabled: bool) -> Dict[str, Any]:
        manifest = self.get_current(user_id=user_id)
        if not manifest.get("avatar_id"):
            return manifest
        manifest["enabled"] = bool(enabled)
        manifest["updated_at"] = int(time.time())
        _atomic_write_json(self._manifest_path(user_id), manifest)
        return manifest

    def clear(self, *, user_id: str) -> Dict[str, Any]:
        manifest = self.get_current(user_id=user_id)
        self._remove_previous_asset(user_id=user_id, previous=manifest)
        self._manifest_path(user_id).unlink(missing_ok=True)
        return self._empty_manifest()

    def get_asset_path(self, *, user_id: str, avatar_id: str) -> Optional[Path]:
        manifest = self.get_current(user_id=user_id)
        if str(manifest.get("avatar_id") or "") != str(avatar_id or ""):
            return None
        stored_name = Path(str(manifest.get("stored_name") or "")).name
        if not stored_name:
            return None
        path = self._asset_dir(user_id) / stored_name
        return path if path.is_file() else None

    def _remove_previous_asset(self, *, user_id: str, previous: Dict[str, Any], keep: str = "") -> None:
        stored_name = Path(str(previous.get("stored_name") or "")).name
        if not stored_name or stored_name == keep:
            return
        (self._asset_dir(user_id) / stored_name).unlink(missing_ok=True)

    def _kind_for_suffix(self, suffix: str) -> str:
        if suffix in self.IMAGE_SUFFIXES:
            return "image"
        if suffix in self.VIDEO_SUFFIXES:
            return "video"
        return ""

    @staticmethod
    def _default_content_type(suffix: str) -> str:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".webm": "video/webm",
            ".mp4": "video/mp4",
        }.get(suffix, "application/octet-stream")

    @staticmethod
    def _empty_manifest() -> Dict[str, Any]:
        return {
            "avatar_id": "",
            "enabled": False,
            "kind": "none",
            "driver": "none",
            "asset_url": "",
            "capabilities": [],
        }


avatar_service = AvatarService()
