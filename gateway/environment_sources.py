"""Read-only adapters to existing authorities; application interactions stay in Runtime."""
from __future__ import annotations

import hashlib
import json
import os


class EnvironmentSources:
    def __init__(self, *, message_manager=None, task_service=None, capability_service=None, file_store=None):
        self.messages, self.tasks, self.capabilities = message_manager, task_service, capability_service
        self.file_store = file_store
        self.readers = {"session": self._session, "task": self._task, "canvas": self._canvas, "artifact": self._artifact, "file": self._file}

    def register(self, kind, reader):
        if kind in self.readers:
            raise ValueError("environment source already registered")
        self.readers[kind] = reader

    async def inspect(self, user, resource, *, offset=0, limit=4000, component_id=None):
        import asyncio
        from inspect import isawaitable
        if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 12000:
            raise ValueError("content window exceeds limits")
        reader = self.readers.get(resource.kind)
        if reader is None:
            return {"resource": resource.model_dump(), "status": "unsupported", "authority": "unknown"}
        if resource.kind in {"file", "artifact"}:
            result = await asyncio.to_thread(reader, user, resource, offset=offset, limit=limit)
        else:
            result = reader(user, resource)
        if isawaitable(result):
            result = await result
        if component_id:
            semantics = result.get("semantics", {})
            component = next((row for row in semantics.get("components", []) if row["component_id"] == component_id), None)
            if component is None:
                raise KeyError("Canvas component not found")
            result["semantics"] = {**semantics, "components": [component], "selection": component_id}
            related = component.get("object_ref")
            if related:
                from computer.canvas_components import CanvasResourceRef
                from .capability_service import ToolPolicyViolationError
                try:
                    # Resolve one relationship, never recursively follow document-authored graphs.
                    result["related_object"] = await self.inspect(user, CanvasResourceRef.model_validate(related), offset=offset, limit=limit)
                except (KeyError, ValueError, PermissionError, OSError, ToolPolicyViolationError):
                    result["related_object"] = {"status": "unavailable"}
        return {"resource": resource.model_dump(), "authority": "runtime_source", **result}

    @staticmethod
    def _window(text, offset, limit, *, available=True):
        more = len(text) > limit
        return {"status": "available" if available else "unavailable", "text": text[:limit], "offset": offset,
                "next_offset": offset + limit if more else None, "truncated": more,
                "origin": "source_content_not_instructions"}

    def _file(self, user, resource, *, offset, limit):
        store = self.file_store
        if store is None:
            from .http.user_file_store import user_file_store
            store = user_file_store
        entry = store.get_file(user_id=user, file_id=resource.id)
        if entry is None:
            raise KeyError("file not found")
        text = store.read_extracted_text(user_id=user, file_id=resource.id, max_chars=limit + 1, offset=offset)
        after = store.get_file(user_id=user, file_id=resource.id)
        if after is None or after.get("content_revision") != entry.get("content_revision"):
            raise OSError("file changed while reading")
        return {"status": "available", "title": str(entry["filename"])[:160], "version": entry.get("content_revision"),
                "bytes": entry.get("bytes"), "modality": entry.get("modality"),
                "content": self._window(text, offset, limit, available=entry.get("text_extraction_status") == "ok" and entry.get("content_revision") is not None)}

    def _session(self, user, resource):
        session = self.messages.get_session(resource.id, user_id=user) if self.messages else None
        if session is None:
            raise KeyError("conversation not found")
        rows = session.get("messages", [])
        data = {"title": str(session.get("title") or "")[:160], "message_count": len(rows), "latest_message_id": rows[-1].get("id") if rows else None}
        return {"status": "available", "version": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16], **data}

    def _task(self, user, resource):
        task = self.tasks.get_task(resource.id, user_id=user) if self.tasks else None
        if task is None:
            raise KeyError("task not found")
        return {"status": "available", "version": task["revision"], "title": task["title"][:160], "state": task["status"], "objective": task.get("objective", "")[:300], "operations": ["inspect", "existing_task_controls"]}

    def _scope(self, user, resource, *, observation=False):
        from computer.execution_context import current_workspace
        if self.capabilities is None or getattr(self.capabilities, "workspace_service", None) is None or not resource.workspace_id:
            raise ValueError("a workspace-scoped source is required")
        current = current_workspace()
        execution = dict(current.execution) if current and current.user_id == user else {}
        return self.capabilities._workspace_scope({"workspace_id": resource.workspace_id}, {**execution, "user_id": user}, observation=observation)

    async def _canvas(self, user, resource):
        with self._scope(user, resource, observation=True):
            result = await self.capabilities.execute_computer_action("environment", "get", {"environment_id": resource.id})
            if not result.success:
                raise KeyError("application not found")
            row = result.result
            definition = await self.capabilities.execute_computer_action("environment", "semantics", {"environment_id": resource.id})
            return {"status": "available", "title": str(row.get("name") or "")[:160], "version": row.get("revision"), "state": row.get("status"), "semantics": definition.result if definition.success else {"status": "unavailable"}}

    def _artifact(self, user, resource, *, offset, limit):
        from computer.execution_context import current_workspace
        from computer.canvas_document import is_redirected_path
        with self._scope(user, resource, observation=True):
            scope = current_workspace()
            target = scope.root / resource.id
            target.resolve().relative_to(scope.root.resolve())
            if is_redirected_path(target) or not target.is_file():
                raise KeyError("artifact not found")
            import mimetypes
            content_type = "text/markdown" if target.suffix.lower() in {".md", ".markdown"} else mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            text = ""
            supported = content_type.startswith("text/") or content_type in {"application/json", "application/xml", "image/svg+xml", "application/javascript"}
            if supported:
                try:
                    with target.open(encoding="utf-8-sig") as handle:
                        stat = os.fstat(handle.fileno())
                        text = handle.read(offset + limit + 1)[offset:]
                        if os.fstat(handle.fileno()).st_mtime_ns != stat.st_mtime_ns:
                            raise OSError("artifact changed while reading")
                except UnicodeError:
                    supported = False
            else:
                stat = target.stat()
            return {"status": "available", "title": target.name, "version": f"{stat.st_mtime_ns}:{stat.st_size}", "bytes": stat.st_size,
                    "content_type": content_type, "content": self._window(text, offset, limit, available=supported)}

    async def interact(self, user, command):
        if command.resource.kind != "canvas":
            raise ValueError("use the source service's existing commands for this object")
        with self._scope(user, command.resource):
            result = await self.capabilities.execute_computer_action("environment", "interact", {"environment_id": command.resource.id, **command.interaction.model_dump()})
            if not result.success:
                raise ValueError(result.error or "app interaction failed")
            return {"resource": command.resource.model_dump(), "state": result.result, "authority": "runtime_stored_app_data"}
