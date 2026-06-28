from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.tool_service import ToolInvocationContext

from .workspace_tools import _resolve_identity, _safe_path_under_root


class ArchiveZipCreateTool:
    tool_id = "archive.zip_create"
    name = "archive.zip_create"
    description = "Create a zip archive from files inside the current workspace."
    official = True
    official_domain = "archive"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        output_path = str((args or {}).get("output_path") or "").strip()
        paths = (args or {}).get("paths") or []
        if not output_path:
            raise ValueError("output_path is required")
        if not isinstance(paths, list) or not paths:
            raise ValueError("paths must be a non-empty list")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        archive = _safe_path_under_root(root, output_path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for raw in paths:
                rel = str(raw or "").strip()
                if not rel:
                    continue
                target = _safe_path_under_root(root, rel)
                candidates = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file()]
                for item in candidates:
                    arcname = str(item.relative_to(root)).replace("\\", "/")
                    if arcname == str(archive.relative_to(root)).replace("\\", "/"):
                        continue
                    zf.write(item, arcname)
                    written.append(arcname)
        return {
            "workspace_id": handle.workspace_id,
            "path": str(archive.relative_to(root)).replace("\\", "/"),
            "count": len(written),
            "files": written,
        }


class ArchiveZipListTool:
    tool_id = "archive.zip_list"
    name = "archive.zip_list"
    description = "List entries in a zip archive inside the current workspace."
    official = True
    official_domain = "archive"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        archive = _safe_path_under_root(root, path)
        if not archive.exists() or not archive.is_file():
            raise FileNotFoundError(f"archive not found: {path}")
        with zipfile.ZipFile(archive, "r") as zf:
            entries = [{"name": info.filename, "size": info.file_size} for info in zf.infolist()]
        return {"workspace_id": handle.workspace_id, "path": path, "count": len(entries), "entries": entries}


class ArchiveZipExtractTool:
    tool_id = "archive.zip_extract"
    name = "archive.zip_extract"
    description = "Extract a zip archive into a workspace subdirectory."
    official = True
    official_domain = "archive"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        dest_dir = str((args or {}).get("dest_dir") or "extracted").strip()
        if not path:
            raise ValueError("path is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        archive = _safe_path_under_root(root, path)
        dest = _safe_path_under_root(root, dest_dir)
        if not archive.exists() or not archive.is_file():
            raise FileNotFoundError(f"archive not found: {path}")
        extracted: List[str] = []
        with zipfile.ZipFile(archive, "r") as zf:
            for info in zf.infolist():
                target = _safe_path_under_root(dest, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info.filename))
                extracted.append(str(target.relative_to(root)).replace("\\", "/"))
        return {
            "workspace_id": handle.workspace_id,
            "dest_dir": str(dest.relative_to(root)).replace("\\", "/"),
            "count": len(extracted),
            "files": extracted,
        }
