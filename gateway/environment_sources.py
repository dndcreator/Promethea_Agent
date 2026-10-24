"""Read-only adapters to existing authorities; application interactions stay in Runtime."""
from __future__ import annotations

import hashlib
import json


class EnvironmentSources:
    def __init__(self, *, message_manager=None, task_service=None, capability_service=None):
        self.messages, self.tasks, self.capabilities = message_manager, task_service, capability_service
        self.readers = {"session": self._session, "task": self._task, "canvas": self._canvas, "artifact": self._artifact}

    def register(self, kind, reader):
        if kind in self.readers:
            raise ValueError("environment source already registered")
        self.readers[kind] = reader

    async def inspect(self, user, resource):
        from inspect import isawaitable
        reader = self.readers.get(resource.kind)
        if reader is None:
            return {"resource": resource.model_dump(), "status": "unsupported", "authority": "unknown"}
        result = reader(user, resource)
        if isawaitable(result):
            result = await result
        return {"resource": resource.model_dump(), "authority": "runtime_source", **result}

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

    def _scope(self, user, resource):
        from computer.execution_context import current_workspace
        if self.capabilities is None or getattr(self.capabilities, "workspace_service", None) is None or not resource.workspace_id:
            raise ValueError("a workspace-scoped source is required")
        current = current_workspace()
        execution = dict(current.execution) if current and current.user_id == user else {}
        return self.capabilities._workspace_scope({"workspace_id": resource.workspace_id}, {**execution, "user_id": user})

    async def _canvas(self, user, resource):
        with self._scope(user, resource):
            result = await self.capabilities.execute_computer_action("environment", "get", {"environment_id": resource.id})
            if not result.success:
                raise KeyError("application not found")
            row = result.result
            definition = await self.capabilities.execute_computer_action("environment", "semantics", {"environment_id": resource.id})
            return {"status": "available", "title": str(row.get("name") or "")[:160], "version": row.get("revision"), "state": row.get("status"), "semantics": definition.result if definition.success else {"status": "unavailable"}}

    def _artifact(self, user, resource):
        from computer.execution_context import current_workspace
        from computer.canvas_document import is_redirected_path
        with self._scope(user, resource):
            scope = current_workspace()
            target = scope.root / resource.id
            target.resolve().relative_to(scope.root.resolve())
            if is_redirected_path(target) or not target.is_file():
                raise KeyError("artifact not found")
            stat = target.stat()
            return {"status": "available", "title": target.name, "version": f"{stat.st_mtime_ns}:{stat.st_size}", "bytes": stat.st_size}

    async def interact(self, user, command):
        if command.resource.kind != "canvas":
            raise ValueError("use the source service's existing commands for this object")
        with self._scope(user, command.resource):
            result = await self.capabilities.execute_computer_action("environment", "interact", {"environment_id": command.resource.id, **command.interaction.model_dump()})
            if not result.success:
                raise ValueError(result.error or "app interaction failed")
            return {"resource": command.resource.model_dump(), "state": result.result, "authority": "runtime_stored_app_data"}
