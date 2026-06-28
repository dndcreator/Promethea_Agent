from __future__ import annotations

import hashlib
import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.tool_service import ToolInvocationContext


def _resolve_identity(
    args: Dict[str, Any],
    ctx: Optional[ToolInvocationContext],
) -> tuple[str, str]:
    user_id = (
        str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip()
        or "default_user"
    )
    workspace_id = (
        str((args or {}).get("workspace_id") or (ctx.session_id if ctx else "") or "default").strip()
        or "default"
    )
    return user_id, workspace_id


def _safe_path_under_root(root: Path, relative_path: str) -> Path:
    target = (root / (relative_path or "")).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except Exception as e:
        raise ValueError(f"path escapes workspace root: {relative_path}") from e
    return target


class WorkspaceListFilesTool:
    tool_id = "workspace.list_files"
    name = "workspace.list_files"
    description = "List files in current workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, workspace_id = _resolve_identity(args, ctx)
        subdir = str((args or {}).get("subdir") or "").strip()
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        files = self.workspace_service.list_artifacts(
            handle=handle,
            subdir=subdir,
            requester_user_id=user_id,
        )
        return {
            "workspace_id": handle.workspace_id,
            "user_id": handle.user_id,
            "subdir": subdir,
            "count": len(files),
            "files": files,
        }


class WorkspaceReadFileTool:
    tool_id = "workspace.read_file"
    name = "workspace.read_file"
    description = "Read a text file from workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        max_chars = int((args or {}).get("max_chars") or 20000)
        max_chars = max(128, min(max_chars, 200000))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        content = target.read_text(encoding="utf-8")
        truncated = len(content) > max_chars
        preview = content[:max_chars]
        return {
            "workspace_id": handle.workspace_id,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "exists": True,
            "size": len(content),
            "truncated": truncated,
            "content": preview,
        }


class WorkspaceWriteFileTool:
    tool_id = "workspace.write_file"
    name = "workspace.write_file"
    description = "Create or update a text file in workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        content = str((args or {}).get("content") or "")
        mode = str((args or {}).get("mode") or "overwrite").strip().lower()
        if mode not in {"overwrite", "append"}:
            raise ValueError("mode must be one of: overwrite, append")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if mode == "append" and target.exists():
            previous = target.read_text(encoding="utf-8")
            next_content = previous + content
        else:
            next_content = content

        write_fn = self.workspace_service.create_document
        if target.exists():
            write_fn = self.workspace_service.update_document
        row = write_fn(
            handle=handle,
            relative_path=str(target.relative_to(root)).replace("\\", "/"),
            content=next_content,
            requester_user_id=user_id,
        )
        row["mode"] = mode
        return row


class WorkspaceCopyFileTool:
    tool_id = "workspace.copy_file"
    name = "workspace.copy_file"
    description = "Copy a file inside workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        src_path = str((args or {}).get("src_path") or "").strip()
        dst_path = str((args or {}).get("dst_path") or "").strip()
        if not src_path or not dst_path:
            raise ValueError("src_path and dst_path are required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        src = _safe_path_under_root(root, src_path)
        dst = _safe_path_under_root(root, dst_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"source not found: {src_path}")
        content = src.read_text(encoding="utf-8")
        row = self.workspace_service.create_document(
            handle=handle,
            relative_path=str(dst.relative_to(root)).replace("\\", "/"),
            content=content,
            requester_user_id=user_id,
        )
        row["copied_from"] = str(src.relative_to(root)).replace("\\", "/")
        return row


class WorkspaceMoveFileTool:
    tool_id = "workspace.move_file"
    name = "workspace.move_file"
    description = "Move or rename a file inside workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        src_path = str((args or {}).get("src_path") or "").strip()
        dst_path = str((args or {}).get("dst_path") or "").strip()
        if not src_path or not dst_path:
            raise ValueError("src_path and dst_path are required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        src = _safe_path_under_root(root, src_path)
        dst = _safe_path_under_root(root, dst_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"source not found: {src_path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return {
            "workspace_id": handle.workspace_id,
            "operation": "move",
            "source_path": str(src_path).replace("\\", "/"),
            "path": str(dst.relative_to(root)).replace("\\", "/"),
        }


class WorkspaceDeleteFileTool:
    tool_id = "workspace.delete_file"
    name = "workspace.delete_file"
    description = "Delete a file from workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        target.unlink()
        return {
            "workspace_id": handle.workspace_id,
            "operation": "delete",
            "path": str(path).replace("\\", "/"),
            "deleted": True,
        }


class WorkspaceSearchTextTool:
    tool_id = "workspace.search_text"
    name = "workspace.search_text"
    description = "Search plain text across workspace files."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        subdir = str((args or {}).get("subdir") or "").strip()
        max_results = int((args or {}).get("max_results") or 20)
        max_results = max(1, min(max_results, 200))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        files = self.workspace_service.list_artifacts(
            handle=handle,
            subdir=subdir,
            requester_user_id=user_id,
        )
        root = Path(handle.root_path)
        hits: List[Dict[str, Any]] = []
        for row in files:
            rel_path = str(row.get("path") or "")
            if not rel_path:
                continue
            target = _safe_path_under_root(root, rel_path)
            try:
                content = target.read_text(encoding="utf-8")
            except Exception:
                continue
            idx = content.find(query)
            if idx < 0:
                continue
            start = max(0, idx - 120)
            end = min(len(content), idx + len(query) + 120)
            hits.append(
                {
                    "path": rel_path.replace("\\", "/"),
                    "index": idx,
                    "preview": content[start:end],
                }
            )
            if len(hits) >= max_results:
                break
        return {
            "workspace_id": handle.workspace_id,
            "query": query,
            "count": len(hits),
            "hits": hits,
        }


class WorkspaceEnsureDirTool:
    tool_id = "workspace.ensure_dir"
    name = "workspace.ensure_dir"
    description = "Create a directory inside workspace if it does not exist."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        dir_path = str((args or {}).get("path") or "").strip()
        if not dir_path:
            raise ValueError("path is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, dir_path)
        target.mkdir(parents=True, exist_ok=True)
        return {
            "workspace_id": handle.workspace_id,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "created": True,
        }


class WorkspaceGlobFilesTool:
    tool_id = "workspace.glob_files"
    name = "workspace.glob_files"
    description = "List files by glob pattern in workspace."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        pattern = str((args or {}).get("pattern") or "**/*").strip() or "**/*"
        max_results = int((args or {}).get("max_results") or 500)
        max_results = max(1, min(max_results, 5000))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        rows: List[Dict[str, Any]] = []
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            rows.append({"path": rel, "size": p.stat().st_size})
            if len(rows) >= max_results:
                break
        return {
            "workspace_id": handle.workspace_id,
            "pattern": pattern,
            "count": len(rows),
            "files": rows,
        }


class WorkspaceReadFilesTool:
    tool_id = "workspace.read_files"
    name = "workspace.read_files"
    description = "Read multiple text files from workspace in one call."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        paths = (args or {}).get("paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError("paths must be a non-empty list")
        max_chars = int((args or {}).get("max_chars_per_file") or 10000)
        max_chars = max(128, min(max_chars, 200000))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        out: List[Dict[str, Any]] = []
        for raw in paths:
            path = str(raw or "").strip()
            if not path:
                continue
            target = _safe_path_under_root(root, path)
            if not target.exists() or not target.is_file():
                out.append({"path": path, "ok": False, "error": "not_found"})
                continue
            try:
                content = target.read_text(encoding="utf-8")
                truncated = len(content) > max_chars
                out.append(
                    {
                        "path": str(target.relative_to(root)).replace("\\", "/"),
                        "ok": True,
                        "size": len(content),
                        "truncated": truncated,
                        "content": content[:max_chars],
                    }
                )
            except Exception as e:
                out.append({"path": path, "ok": False, "error": str(e)})
        return {"workspace_id": handle.workspace_id, "count": len(out), "items": out}


class WorkspaceFileInfoTool:
    tool_id = "workspace.file_info"
    name = "workspace.file_info"
    description = "Return metadata and digest for a workspace file."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        digest_algo = str((args or {}).get("digest") or "sha256").strip().lower()
        if digest_algo not in {"sha1", "sha256", "md5"}:
            raise ValueError("digest must be one of: sha1, sha256, md5")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        data = target.read_bytes()
        h = hashlib.new(digest_algo)
        h.update(data)
        return {
            "workspace_id": handle.workspace_id,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "size": len(data),
            "updated_at": target.stat().st_mtime,
            "digest_algo": digest_algo,
            "digest": h.hexdigest(),
        }


class WorkspaceTailFileTool:
    tool_id = "workspace.tail_file"
    name = "workspace.tail_file"
    description = "Read tail lines from a text file."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        lines = int((args or {}).get("lines") or 50)
        lines = max(1, min(lines, 2000))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        content = target.read_text(encoding="utf-8")
        parts = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        tail = parts[-lines:]
        return {
            "workspace_id": handle.workspace_id,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "lines": len(tail),
            "content": "\n".join(tail),
        }


class WorkspaceReplaceTextTool:
    tool_id = "workspace.replace_text"
    name = "workspace.replace_text"
    description = "Replace text or regex pattern in a workspace file."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        pattern = str((args or {}).get("pattern") or "")
        replacement = str((args or {}).get("replacement") or "")
        if not path:
            raise ValueError("path is required")
        if pattern == "":
            raise ValueError("pattern is required")
        regex = bool((args or {}).get("regex", False))
        case_sensitive = bool((args or {}).get("case_sensitive", True))
        max_replacements = int((args or {}).get("max_replacements") or 0)
        max_replacements = max(0, min(max_replacements, 100000))
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        original = target.read_text(encoding="utf-8")
        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            repl_count = 0 if max_replacements <= 0 else max_replacements
            updated, changed = re.subn(pattern, replacement, original, count=repl_count, flags=flags)
        else:
            src = original if case_sensitive else original.lower()
            needle = pattern if case_sensitive else pattern.lower()
            if max_replacements <= 0:
                changed = src.count(needle)
                if case_sensitive:
                    updated = original.replace(pattern, replacement)
                else:
                    updated, changed = re.subn(re.escape(pattern), replacement, original, flags=re.IGNORECASE)
            else:
                if case_sensitive:
                    updated = original.replace(pattern, replacement, max_replacements)
                    changed = min(original.count(pattern), max_replacements)
                else:
                    updated, changed = re.subn(
                        re.escape(pattern),
                        replacement,
                        original,
                        count=max_replacements,
                        flags=re.IGNORECASE,
                    )
        row = self.workspace_service.update_document(
            handle=handle,
            relative_path=str(target.relative_to(root)).replace("\\", "/"),
            content=updated,
            requester_user_id=user_id,
        )
        row["replacements"] = int(changed)
        return row


class WorkspaceDiffFileTool:
    tool_id = "workspace.diff_file"
    name = "workspace.diff_file"
    description = "Create a unified diff between a workspace file and proposed content."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        proposed = str((args or {}).get("content") or "")
        if not path:
            raise ValueError("path is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        original = target.read_text(encoding="utf-8") if target.exists() and target.is_file() else ""
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return {
            "workspace_id": handle.workspace_id,
            "path": str(path).replace("\\", "/"),
            "exists": target.exists(),
            "changed": original != proposed,
            "diff": diff,
        }


class WorkspaceApplyPatchTool:
    tool_id = "workspace.apply_patch"
    name = "workspace.apply_patch"
    description = "Apply a simple text patch by replacing exact old text with new text in a workspace file."
    official = True
    official_domain = "workspace"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        path = str((args or {}).get("path") or "").strip()
        old_text = str((args or {}).get("old_text") or "")
        new_text = str((args or {}).get("new_text") or "")
        if not path:
            raise ValueError("path is required")
        if old_text == "":
            raise ValueError("old_text is required")
        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = _safe_path_under_root(root, path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        original = target.read_text(encoding="utf-8")
        count = original.count(old_text)
        if count != 1:
            raise ValueError(f"old_text must match exactly once, matched {count}")
        updated = original.replace(old_text, new_text, 1)
        row = self.workspace_service.update_document(
            handle=handle,
            relative_path=str(target.relative_to(root)).replace("\\", "/"),
            content=updated,
            requester_user_id=user_id,
        )
        row["patched"] = True
        return row
