from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .events import EventEmitter
from .protocol import EventType


class WorkspaceHandle(BaseModel):
    workspace_id: str
    user_id: str
    root_path: str
    permissions: Dict[str, Any] = Field(default_factory=lambda: {"read": True, "write": True})
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceSandboxError(Exception):
    pass


class WorkspaceService:
    def __init__(
        self,
        *,
        event_emitter: Optional[EventEmitter] = None,
        base_dir: Optional[str] = None,
    ) -> None:
        self.event_emitter = event_emitter
        default_base = Path(__file__).resolve().parents[1] / "workspace"
        self.base_dir = Path(base_dir or default_base)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def resolve_workspace_handle(
        self,
        *,
        user_id: str,
        workspace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        permissions: Optional[Dict[str, Any]] = None,
    ) -> WorkspaceHandle:
        wid = str(workspace_id or "default").strip() or "default"
        uid = str(user_id or "default_user").strip() or "default_user"
        safe_uid = self._safe_segment(uid)
        safe_wid = self._safe_segment(wid)
        root = self.base_dir / safe_uid / safe_wid
        root.mkdir(parents=True, exist_ok=True)
        return WorkspaceHandle(
            workspace_id=safe_wid,
            user_id=safe_uid,
            root_path=str(root),
            permissions=dict(permissions or {"read": True, "write": True}),
            metadata=dict(metadata or {}),
        )

    def create_document(
        self,
        *,
        handle: WorkspaceHandle,
        relative_path: str,
        content: str,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        requester_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_owner(
            handle=handle,
            requester_user_id=requester_user_id,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="create",
            path=relative_path,
        )
        return self._write_artifact(
            handle=handle,
            relative_path=relative_path,
            content=content,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="create",
        )

    def update_document(
        self,
        *,
        handle: WorkspaceHandle,
        relative_path: str,
        content: str,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        requester_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_owner(
            handle=handle,
            requester_user_id=requester_user_id,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="update",
            path=relative_path,
        )
        return self._write_artifact(
            handle=handle,
            relative_path=relative_path,
            content=content,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="update",
        )

    def list_artifacts(
        self,
        *,
        handle: WorkspaceHandle,
        subdir: str = "",
        requester_user_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._assert_owner(
            handle=handle,
            requester_user_id=requester_user_id,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="list",
            path=subdir,
        )
        root = Path(handle.root_path)
        base = self._resolve_under_root(root, subdir or ".")
        rows: List[Dict[str, Any]] = []
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rows.append(
                {
                    "path": str(p.relative_to(root)).replace("\\", "/"),
                    "size": p.stat().st_size,
                    "updated_at": datetime.utcfromtimestamp(p.stat().st_mtime).isoformat() + "Z",
                }
            )
        return rows

    def snapshot_artifact(
        self,
        *,
        handle: WorkspaceHandle,
        relative_path: str,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        requester_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_owner(
            handle=handle,
            requester_user_id=requester_user_id,
            trace_id=trace_id,
            request_id=request_id,
            session_id=session_id,
            operation="snapshot",
            path=relative_path,
        )
        root = Path(handle.root_path)
        src = self._resolve_under_root(root, relative_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"artifact not found: {relative_path}")
        snap_dir = root / ".snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        snap_name = f"{ts}__{src.name}"
        dst = snap_dir / snap_name
        shutil.copy2(src, dst)

        payload = {
            "workspace_id": handle.workspace_id,
            "user_id": handle.user_id,
            "operation": "snapshot",
            "source_path": str(src.relative_to(root)).replace("\\", "/"),
            "snapshot_path": str(dst.relative_to(root)).replace("\\", "/"),
            "trace_id": trace_id,
            "request_id": request_id,
            "session_id": session_id,
        }
        self._emit_event(EventType.WORKSPACE_ARTIFACT_WRITTEN, payload)
        return payload

    def _write_artifact(
        self,
        *,
        handle: WorkspaceHandle,
        relative_path: str,
        content: str,
        trace_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        operation: str,
    ) -> Dict[str, Any]:
        root = Path(handle.root_path)
        if not bool(handle.permissions.get("write", False)):
            payload = {
                "workspace_id": handle.workspace_id,
                "user_id": handle.user_id,
                "operation": operation,
                "path": relative_path,
                "reason": "workspace_read_only",
                "trace_id": trace_id,
                "request_id": request_id,
                "session_id": session_id,
            }
            self._emit_event(EventType.WORKSPACE_WRITE_BLOCKED, payload)
            raise WorkspaceSandboxError("workspace is read-only")

        target = self._resolve_under_root(root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")

        payload = {
            "workspace_id": handle.workspace_id,
            "user_id": handle.user_id,
            "operation": operation,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "size": target.stat().st_size,
            "trace_id": trace_id,
            "request_id": request_id,
            "session_id": session_id,
        }
        self._emit_event(EventType.WORKSPACE_ARTIFACT_WRITTEN, payload)
        return payload

    def _assert_owner(
        self,
        *,
        handle: WorkspaceHandle,
        requester_user_id: Optional[str],
        trace_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        operation: str,
        path: Optional[str],
    ) -> None:
        if not requester_user_id:
            return
        if str(handle.user_id) == str(requester_user_id):
            return
        payload = {
            "namespace": "workspace",
            "workspace_id": handle.workspace_id,
            "owner_user_id": handle.user_id,
            "requester_user_id": str(requester_user_id),
            "operation": operation,
            "path": str(path or ""),
            "reason": "cross_user_workspace_access",
            "outcome": "blocked",
            "trace_id": trace_id,
            "request_id": request_id,
            "session_id": session_id,
            "user_id": str(requester_user_id),
        }
        self._emit_event(EventType.SECURITY_BOUNDARY_VIOLATION, payload)
        raise WorkspaceSandboxError("forbidden workspace access")

    def _resolve_under_root(self, root: Path, relative_path: str) -> Path:
        target = (root / (relative_path or "")).resolve()
        root_resolved = root.resolve()
        try:
            target.relative_to(root_resolved)
        except Exception as e:
            raise WorkspaceSandboxError(f"path escapes workspace root: {relative_path}") from e
        return target

    def _emit_event(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        import asyncio

        async def _emit() -> None:
            await self.event_emitter.emit(event_type, payload)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit())
        except Exception:
            pass

    @staticmethod
    def _safe_segment(value: str) -> str:
        s = str(value or "").strip()
        if not s:
            return "default"
        keep = []
        for ch in s:
            if ch.isalnum() or ch in ("-", "_", "."):
                keep.append(ch)
            else:
                keep.append("_")
        return "".join(keep)[:80] or "default"

    def dumps_handle(self, handle: WorkspaceHandle) -> str:
        return json.dumps(handle.model_dump(), ensure_ascii=False)
