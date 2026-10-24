"""Append-only capability evolution for Promethea.

Self Evolve may author and publish isolated capability packages. It cannot
patch Python Core or any other existing project file.
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agentkit.mcp.invocation_context import get_invocation_context
from gateway.tools.presentation import validate_presentation_declaration

from .generated_runtime import GeneratedCapabilityService
from .canvas import CanvasSpec, artifact_files, verify_canvas
from computer.canvas_components import CanvasDocument, render_component_document


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-_][a-z0-9]+)?$")
_COMMAND = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_WRITABLE_SUFFIXES = {".py", ".json", ".md", ".txt", ".html", ".css", ".js", ".svg", ".ts", ".tsx", ".jsx"}
_RESERVED_FILES = {"agent-manifest.json", ".published.json"}
_SCAFFOLD_MARKER = "raise NotImplementedError"
_STORE_LOCKS: Dict[str, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


def _store_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(key, threading.RLock())


class SelfEvolveService:
    """Create, verify and publish versioned capabilities without editing Core."""

    def __init__(self, workspace_root: Optional[str] = None, self_model_service: Optional[Any] = None):
        self.name = "self_evolve"
        self.workspace_root = (Path(workspace_root) if workspace_root else Path.cwd()).resolve()
        self.store_path = self.workspace_root / "memory" / "self_evolve_tasks.json"
        self.staging_root = self.workspace_root / ".runtime" / "self-evolve" / "staging"
        self.publish_root = self.workspace_root / "extensions" / "community" / "_generated"
        self.self_model_service = self_model_service
        self._extension_reloader: Optional[Callable[..., List[str]]] = None
        self._capability_runtime: Optional[Any] = None
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.publish_root.mkdir(parents=True, exist_ok=True)

    def configure_extension_reloader(self, reloader: Callable[..., List[str]]) -> None:
        self._extension_reloader = reloader

    def configure_canvas_runtime(self, runtime: Any) -> None:
        self._capability_runtime = runtime

    def _lock(self) -> threading.RLock:
        return _store_lock(self.store_path)

    @staticmethod
    def _current_user_id() -> str:
        user_id = str(get_invocation_context().get("user_id") or "").strip()
        if not user_id:
            raise PermissionError("self-evolve requires an authenticated user context")
        return user_id

    def _load_tasks(self) -> Dict[str, Any]:
        with self._lock():
            if not self.store_path.exists():
                return {"tasks": {}}
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"self-evolve task store is unreadable: {exc}") from exc
            if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), dict):
                raise RuntimeError("self-evolve task store has an invalid structure")
            return raw

    def _save_tasks(self, state: Dict[str, Any]) -> None:
        with self._lock():
            temporary = self.store_path.with_name(f".{self.store_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.store_path)
            finally:
                temporary.unlink(missing_ok=True)

    def _get_task_or_raise(self, task_id: str) -> Dict[str, Any]:
        task = self._load_tasks().get("tasks", {}).get(task_id)
        if not isinstance(task, dict) or task.get("owner_user_id") != self._current_user_id():
            raise FileNotFoundError(f"task not found: {task_id}")
        return task

    def _update_task(self, task_id: str, updater) -> Dict[str, Any]:
        with self._lock():
            state = self._load_tasks()
            task = state.get("tasks", {}).get(task_id)
            if not isinstance(task, dict) or task.get("owner_user_id") != self._current_user_id():
                raise FileNotFoundError(f"task not found: {task_id}")
            updater(task)
            task["updated_at"] = time.time()
            self._save_tasks(state)
            return task

    def _task_root(self, task_id: str) -> Path:
        root = (self.staging_root / str(task_id)).resolve()
        try:
            root.relative_to(self.staging_root.resolve())
        except ValueError as exc:
            raise PermissionError("invalid capability task path") from exc
        return root

    def _task_file(self, task_id: str, relative_path: str) -> Path:
        rel = Path(str(relative_path or ""))
        if not relative_path or rel.is_absolute() or ".." in rel.parts:
            raise ValueError("path must be relative to the capability staging directory")
        if rel.as_posix() in _RESERVED_FILES:
            raise PermissionError(f"system-owned capability file cannot be edited: {rel.as_posix()}")
        if rel.suffix.lower() not in _WRITABLE_SUFFIXES:
            raise ValueError(f"unsupported capability file type: {rel.suffix or '<none>'}")
        path = (self._task_root(task_id) / rel).resolve()
        try:
            path.relative_to(self._task_root(task_id))
        except ValueError as exc:
            raise PermissionError("capability file escaped its staging directory") from exc
        return path

    @staticmethod
    def _normalize_commands(commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(commands, list) or not commands:
            raise ValueError("commands must contain at least one command specification")
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for raw in commands:
            if not isinstance(raw, dict):
                raise ValueError("each command specification must be an object")
            name = str(raw.get("command") or raw.get("name") or "").strip().lower()
            if not _COMMAND.fullmatch(name):
                raise ValueError(f"invalid command name: {name or '<empty>'}")
            if name in seen:
                raise ValueError(f"duplicate command name: {name}")
            seen.add(name)
            description = str(raw.get("description") or "").strip()
            if not description:
                raise ValueError(f"command description is required: {name}")
            if not isinstance(raw.get("test_args"), dict):
                raise ValueError(f"command test_args must be an object: {name}")
            test_args = dict(raw["test_args"])
            presentation = validate_presentation_declaration(raw.get("presentation"))
            normalized.append({
                "command": name,
                "description": description,
                "test_args": test_args,
                **({"expected_result": raw["expected_result"]} if "expected_result" in raw else {}),
                **({"presentation": presentation} if presentation else {}),
            })
        return normalized

    @staticmethod
    def _scaffold(commands: List[Dict[str, Any]]) -> str:
        names = ", ".join(repr(row["command"]) for row in commands)
        return (
            '"""Generated Promethea capability. Executed in an isolated child process."""\n\n'
            "from __future__ import annotations\n\n"
            "from typing import Any\n\n\n"
            "async def handle(command: str, args: dict[str, Any]) -> Any:\n"
            f"    if command not in {{{names}}}:\n"
            "        raise ValueError(f\"unsupported command: {command}\")\n"
            "    raise NotImplementedError(\"implement generated capability\")\n"
        )

    async def evolve_build_self_model(self, max_chars_per_file: int = 5000) -> Dict[str, Any]:
        if self.self_model_service is None:
            raise RuntimeError("self_model_service is required")
        return await self.self_model_service.build_self_model(max_chars_per_file=max_chars_per_file)

    async def evolve_get_self_model(self) -> Dict[str, Any]:
        if self.self_model_service is None:
            return {"exists": False, "reason": "self_model_service_unavailable"}
        return await self.self_model_service.get_self_model()

    async def evolve_get_canvas_schema(self) -> Dict[str, Any]:
        """Inspect the component grammar without expanding every model request."""
        return {"version": "canvas.ui.v1", "schema": CanvasDocument.model_json_schema(),
                "workflow": "Create a canvas task with browser tests; compose its document, validate, then open. Interactions only update app state, never execute Runtime tools."}

    async def evolve_compose_canvas(self, task_id: str, document: Dict[str, Any], expected_sha256: Optional[str] = None) -> Dict[str, Any]:
        """Compile a bounded component document using the trusted Canvas renderer."""
        task = self._get_task_or_raise(task_id)
        if not task.get("canvas"):
            raise ValueError("component documents require a canvas application task")
        if Path(task["canvas"]["entrypoint"]).suffix.lower() != ".html":
            raise ValueError("component documents require an HTML entrypoint")
        html = render_component_document(document)
        result = await self.evolve_write_file(task_id, task["canvas"]["entrypoint"], html, expected_sha256=expected_sha256)
        from computer.canvas_semantics import snapshot
        semantics = snapshot(html, {"value": {}, "revision": 0})
        return {**result, "semantics": {"status": semantics["status"], "component_count": len(semantics["components"]), "definition_revision": semantics["definition_revision"], "browser_verified": False}}

    async def evolve_create_task(
        self,
        goal: str,
        capability_id: str,
        version: str,
        description: str,
        commands: Optional[List[Dict[str, Any]]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        canvas: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        goal = str(goal or "").strip()
        capability_id = str(capability_id or "").strip().lower().replace("-", "_")
        version = str(version or "").strip().lower()
        description = str(description or "").strip()
        if not goal:
            raise ValueError("goal is required")
        if not _IDENTIFIER.fullmatch(capability_id):
            raise ValueError("capability_id must be a lowercase identifier with 2-48 characters")
        if not _VERSION.fullmatch(version):
            raise ValueError("version must use a simple semantic version such as 1.0.0")
        if not description:
            raise ValueError("description is required")
        canvas_spec = CanvasSpec.model_validate(canvas).model_dump() if canvas is not None else None
        if canvas_spec and commands:
            raise ValueError("canvas artifacts and callable tools are separate package kinds")
        normalized_commands = [] if canvas_spec else self._normalize_commands(commands)
        owner_user_id = self._current_user_id()

        task_id = f"se_{uuid.uuid4().hex}"
        root = self._task_root(task_id)
        root.mkdir(parents=True, exist_ok=False)
        scaffold = self._scaffold(normalized_commands)
        if not canvas_spec:
            (root / "tool.py").write_text(scaffold, encoding="utf-8")

        now = time.time()
        task = {
            "task_id": task_id,
            "kind": "canvas_application" if canvas_spec else "capability_package",
            "canvas": canvas_spec,
            "owner_user_id": owner_user_id,
            "goal": goal,
            "capability_id": capability_id,
            "version": version,
            "description": description,
            "commands": normalized_commands,
            "acceptance_criteria": [str(x) for x in (acceptance_criteria or []) if str(x).strip()],
            "status": "draft",
            "staging_path": root.relative_to(self.workspace_root).as_posix(),
            "changes": [] if canvas_spec else [{"ts": now, "op": "scaffold", "path": "tool.py"}],
            "validations": [],
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self._lock():
                state = self._load_tasks()
                state.setdefault("tasks", {})[task_id] = task
                self._save_tasks(state)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return {"ok": True, "task": task, "scaffold": scaffold}

    async def evolve_get_task(self, task_id: str) -> Dict[str, Any]:
        return {"ok": True, "task": self._get_task_or_raise(task_id)}

    async def evolve_list_tasks(self, limit: int = 20, status: str = "") -> Dict[str, Any]:
        owner_user_id = self._current_user_id()
        rows = [
            row for row in self._load_tasks().get("tasks", {}).values()
            if isinstance(row, dict) and row.get("owner_user_id") == owner_user_id
        ]
        status_filter = str(status or "").strip().lower()
        if status_filter:
            rows = [row for row in rows if str(row.get("status") or "").lower() == status_filter]
        rows.sort(key=lambda row: float(row.get("updated_at", 0)), reverse=True)
        rows = rows[: max(1, int(limit))]
        return {"ok": True, "total": len(rows), "tasks": rows}

    async def evolve_collect_context(self, task_id: str, max_chars_per_file: int = 4000) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        cap = max(200, int(max_chars_per_file))
        root = self._task_root(task_id)
        files = []
        for path in artifact_files(root):
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "content": path.read_text(encoding="utf-8", errors="replace")[:cap],
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        return {"ok": True, "task": task, "files": files}

    async def evolve_write_file(self, task_id: str, path: str, content: str, expected_sha256: Optional[str] = None) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        if task.get("status") == "published":
            raise PermissionError("published capability versions are immutable")
        payload = str(content)
        if len(payload.encode("utf-8")) > 256_000:
            raise ValueError("capability file exceeds 256 KB")
        file_path = self._task_file(task_id, path)
        relative = file_path.relative_to(self._task_root(task_id)).as_posix()

        def _record(row: Dict[str, Any]) -> None:
            row.setdefault("changes", []).append(
                {"ts": time.time(), "op": "write", "path": relative, "bytes": len(payload.encode("utf-8"))}
            )
            row["status"] = "draft"
            row.pop("validated_digest", None)
            row["revision"] = int(row.get("revision") or 0) + 1

        with self._lock():
            task = self._get_task_or_raise(task_id)
            if task.get("status") == "published":
                raise PermissionError("published capability versions are immutable")
            actual = hashlib.sha256(file_path.read_bytes()).hexdigest() if file_path.exists() else ""
            if expected_sha256 is not None and actual != expected_sha256:
                raise ValueError("file changed since inspection; read it again before editing")
            self._checkpoint(task_id)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(payload, encoding="utf-8")
            self._update_task(task_id, _record)
        return {"ok": True, "task_id": task_id, "path": relative, "bytes": len(payload.encode("utf-8"))}

    async def evolve_read_file(self, task_id: str, path: str, start_line: int = 1, end_line: int = 200) -> Dict[str, Any]:
        self._get_task_or_raise(task_id)
        data = self._task_file(task_id, path).read_bytes()
        lines = data.decode("utf-8").splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), max(start, min(int(end_line), start + 399)))
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "total_lines": len(lines),
                "content": "\n".join(f"{index + 1}: {lines[index]}" for index in range(start - 1, end))[:24000]}

    async def evolve_search(self, task_id: str, query: str) -> Dict[str, Any]:
        self._get_task_or_raise(task_id)
        if not query:
            raise ValueError("search query is required")
        root = self._task_root(task_id)
        matches = []
        for path in artifact_files(root):
            for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({"path": path.relative_to(root).as_posix(), "line": index, "text": line[:500]})
                    if len(matches) == 100:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    async def evolve_delete_file(self, task_id: str, path: str, expected_sha256: str) -> Dict[str, Any]:
        with self._lock():
            task = self._get_task_or_raise(task_id)
            if task["status"] == "published":
                raise PermissionError("published versions are immutable")
            target = self._task_file(task_id, path)
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
                raise ValueError("file changed since inspection")
            self._checkpoint(task_id)
            target.unlink()
            def invalidate(row):
                row.update(status="draft", revision=row["revision"] + 1)
                row.pop("validated_digest", None)
            self._update_task(task_id, invalidate)
        return {"ok": True, "path": path}

    def _checkpoint(self, task_id: str) -> str:
        task = self._get_task_or_raise(task_id)
        checkpoint_id = f"cp_{uuid.uuid4().hex}"
        root = self.staging_root.parent / "checkpoints" / task_id / checkpoint_id
        root.mkdir(parents=True)
        for path in artifact_files(self._task_root(task_id)):
            target = root / path.relative_to(self._task_root(task_id))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        def record(row):
            rows = row.setdefault("checkpoints", [])
            rows.append({"checkpoint_id": checkpoint_id, "revision": task["revision"], "at": time.time()})
            while len(rows) > 20:
                old = rows.pop(0)
                shutil.rmtree(root.parent / old["checkpoint_id"])
        self._update_task(task_id, record)
        return checkpoint_id

    async def evolve_review(self, task_id: str, checkpoint_id: str = "") -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        checkpoints = task.get("checkpoints", [])
        selected = next((row for row in checkpoints if row["checkpoint_id"] == checkpoint_id), None) if checkpoint_id else (checkpoints[-1] if checkpoints else None)
        if checkpoint_id and not selected:
            raise FileNotFoundError("checkpoint not found")
        if not selected:
            return {"ok": True, "checkpoints": checkpoints, "diff": ""}
        before = self.staging_root.parent / "checkpoints" / task_id / selected["checkpoint_id"]
        current = self._task_root(task_id)
        names = {p.relative_to(before).as_posix() for p in artifact_files(before)} | {p.relative_to(current).as_posix() for p in artifact_files(current)}
        diff = []
        for name in sorted(names):
            old = (before / name).read_text(encoding="utf-8").splitlines(True) if (before / name).exists() else []
            new = (current / name).read_text(encoding="utf-8").splitlines(True) if (current / name).exists() else []
            diff.extend(difflib.unified_diff(old, new, fromfile=f"before/{name}", tofile=f"after/{name}"))
        return {"ok": True, "checkpoint_id": selected["checkpoint_id"], "checkpoints": checkpoints, "diff": "".join(diff)[:24000]}

    async def evolve_restore(self, task_id: str, checkpoint_id: str) -> Dict[str, Any]:
        with self._lock():
            task = self._get_task_or_raise(task_id)
            if task["status"] == "published":
                raise PermissionError("published versions are immutable")
            if checkpoint_id not in {r["checkpoint_id"] for r in task.get("checkpoints", [])}:
                raise FileNotFoundError("checkpoint not found")
            before = self.staging_root.parent / "checkpoints" / task_id / checkpoint_id
            snapshot = {path.relative_to(before): path.read_bytes() for path in artifact_files(before)}
            self._checkpoint(task_id)
            current = self._task_root(task_id)
            for path in artifact_files(current):
                path.unlink()
            for relative, data in snapshot.items():
                target = current / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            def restored(row):
                row.update(status="draft", revision=row["revision"] + 1)
                row.pop("validated_digest", None)
            self._update_task(task_id, restored)
        return {"ok": True, "task_id": task_id}

    async def evolve_patch_file(self, task_id: str, path: str, old_text: str, new_text: str, expected_sha256: str) -> Dict[str, Any]:
        with self._lock():
            self._get_task_or_raise(task_id)
            source = self._task_file(task_id, path).read_text(encoding="utf-8")
            if not old_text or source.count(old_text) != 1:
                raise ValueError("patch must match exactly one occurrence")
            return await self.evolve_write_file(task_id, path, source.replace(old_text, new_text, 1), expected_sha256)

    def _service_name(self, task: Dict[str, Any]) -> str:
        version_slug = re.sub(r"[^a-z0-9]+", "_", str(task["version"]).lower()).strip("_")
        owner_slug = hashlib.sha256(str(task["owner_user_id"]).encode("utf-8")).hexdigest()[:10]
        return f"generated_u{owner_slug}_{task['capability_id']}_v{version_slug}"

    def _manifest(self, task: Dict[str, Any]) -> Dict[str, Any]:
        service_name = self._service_name(task)
        if task.get("canvas"):
            return {"name": service_name, "version": task["version"], "canvasApplication": task["canvas"], "ownerUserId": task["owner_user_id"]}
        commands = [
            {
                "command": row["command"],
                "description": row["description"],
                "sideEffectLevel": "privileged_host_action",
                "ownerUserId": task["owner_user_id"],
                **({"presentation": row["presentation"]} if row.get("presentation") else {}),
            }
            for row in task["commands"]
        ]
        return {
            "name": service_name,
            "label": str(task["capability_id"]).replace("_", " ").title(),
            "version": task["version"],
            "description": task["description"],
            "serviceType": "extension_tool",
            "generatedCapability": {
                "formatVersion": 1,
                "capabilityId": task["capability_id"],
                "entryScript": "tool.py",
                "timeoutSeconds": 30,
                "immutable": True,
                "ownerUserId": task["owner_user_id"],
            },
            "capabilities": {"invocation_commands": commands},
            "inputSchema": {"type": "object", "additionalProperties": True},
        }

    @staticmethod
    def _tree_digest(root: Path, manifest: Dict[str, Any]) -> str:
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=True).encode("utf-8"))
        for path in artifact_files(root):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    async def evolve_validate(self, task_id: str) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        if task["status"] == "published":
            raise PermissionError("published versions are immutable; create a new version")
        if task.get("canvas"):
            return await self._validate_canvas(task)
        task_revision = int(task.get("revision") or 0)
        root = self._task_root(task_id)
        entry = root / "tool.py"
        errors: List[str] = []
        smoke_results: List[Dict[str, Any]] = []
        if not entry.is_file():
            errors.append("tool.py is required")
        else:
            source = entry.read_text(encoding="utf-8", errors="replace")
            if _SCAFFOLD_MARKER in source:
                errors.append("tool.py still contains the unimplemented scaffold")
            try:
                tree = ast.parse(source, filename="tool.py")
                handlers = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "handle"]
                if not handlers:
                    errors.append("tool.py must export handle(command, args)")
            except SyntaxError as exc:
                errors.append(f"tool.py syntax error: {exc.msg} at line {exc.lineno}")

        for path in artifact_files(root):
            if path.suffix == ".py" and path != entry:
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=path.relative_to(root).as_posix())
                except SyntaxError as exc:
                    errors.append(f"{path.name}: {exc.msg} at line {exc.lineno}")

        package_files = [path for path in root.rglob("*") if path.is_file() and path.name not in _RESERVED_FILES]
        if any(path.is_symlink() for path in package_files):
            errors.append("capability packages cannot contain symbolic links")
        file_count = len(package_files)
        total_bytes = sum(path.stat().st_size for path in package_files)
        if file_count > 32:
            errors.append("capability package exceeds 32 files")
        if total_bytes > 1_000_000:
            errors.append("capability package exceeds 1 MB")

        validation_digest = self._tree_digest(root, self._manifest(task)) if not errors else None
        if not errors:
            preview_manifest = self._manifest(task)
            preview_path = root / "agent-manifest.json"
            preview_path.write_text(json.dumps(preview_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            service = GeneratedCapabilityService(
                manifest=preview_manifest,
                manifest_path=preview_path,
                runtime_root=self.workspace_root / ".runtime" / "self-evolve" / "validation" / task_id,
            )
            try:
                for row in task["commands"]:
                    try:
                        value = await service.invoke(row["command"], dict(row["test_args"]), require_approval=False)
                        if "expected_result" in row and value != row["expected_result"]:
                            raise ValueError(f"expected {row['expected_result']!r}, received {value!r}")
                        smoke_results.append({"command": row["command"], "ok": True, "result": value})
                    except Exception as exc:
                        smoke_results.append({"command": row["command"], "ok": False, "error": str(exc)})
                        errors.append(f"smoke test failed for {row['command']}: {exc}")
            finally:
                preview_path.unlink(missing_ok=True)

        if validation_digest and self._tree_digest(root, self._manifest(task)) != validation_digest:
            errors.append("capability changed while validation was running")

        ok = not errors
        validated_digest = validation_digest if ok else None

        def _record(row: Dict[str, Any]) -> None:
            if int(row.get("revision") or 0) != task_revision:
                raise ValueError("capability changed while validation was running")
            row.setdefault("validations", []).append(
                {
                    "ts": time.time(),
                    "ok": ok,
                    "errors": errors,
                    "smoke_tests": smoke_results,
                    "package_digest": validated_digest,
                }
            )
            row["status"] = "validated" if ok else "failed_validation"
            if validated_digest:
                row["validated_digest"] = validated_digest
            else:
                row.pop("validated_digest", None)

        self._update_task(task_id, _record)
        return {"ok": ok, "task_id": task_id, "errors": errors, "smoke_tests": smoke_results}

    async def _validate_canvas(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task["task_id"]
        root = self._task_root(task_id)
        digest = self._tree_digest(root, self._manifest(task))
        from config import config
        settings = config.self_evolve.model_dump()
        provider = getattr(self._capability_runtime, "config_provider", None)
        if callable(provider):
            settings.update((provider(self._current_user_id()) or {}).get("self_evolve") or {})
        try:
            from computer.browser_runtime import setup_timeout
            result = await asyncio.wait_for(verify_canvas(root, task["canvas"], self.staging_root.parent / "validation" / task_id / "preview.png", browser_channel=settings["browser_channel"]), 45 + setup_timeout())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {"ok": False, "errors": [str(exc)[:4000]], "steps": []}
        if self._tree_digest(root, self._manifest(task)) != digest:
            result = {**result, "ok": False, "errors": [*result["errors"], "canvas changed during validation"]}
        def record(row):
            if row["revision"] != task["revision"]:
                raise ValueError("canvas changed during validation")
            row.setdefault("validations", []).append({"ts": time.time(), "package_digest": digest, **result})
            row["status"] = "validated" if result["ok"] else "failed_validation"
            row.pop("validated_digest", None)
            if result["ok"]:
                row["validated_digest"] = digest
        self._update_task(task_id, record)
        return {"task_id": task_id, **result}

    async def evolve_run_check(self, task_id: str, argv: List[str], timeout: int = 30) -> Dict[str, Any]:
        from agentkit.security.process_sandbox import SandboxedProcessRunner
        task = self._get_task_or_raise(task_id)
        if task["status"] == "published":
            raise PermissionError("published versions are immutable")
        root = self._task_root(task_id)
        self._checkpoint(task_id)
        try:
            process = await SandboxedProcessRunner().run_async(argv, cwd=root, workspace_root=root, timeout=max(1, min(timeout, 120)))
            result = {"ok": process.returncode == 0, "exit_code": process.returncode,
                      "stdout": (process.stdout or "")[-12000:], "stderr": (process.stderr or "")[-12000:]}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {"ok": False, "error": str(exc)[:4000]}
        finally:
            def invalidate(row):
                row.update(status="draft", revision=row["revision"] + 1)
                row.pop("validated_digest", None)
            self._update_task(task_id, invalidate)
        self._update_task(task_id, lambda row: row.setdefault("checks", []).append({"ts": time.time(), "argv": argv, **result}))
        return result

    async def evolve_open_canvas(self, task_id: str, reusable: bool = False) -> Dict[str, Any]:
        from computer.execution_context import current_workspace, bind_workspace
        runtime = self._capability_runtime
        scope = current_workspace()
        task = self._get_task_or_raise(task_id)
        if not task.get("canvas") or task["status"] not in {"validated", "published"}:
            raise ValueError("a canvas must pass browser verification before opening")
        if runtime is None or scope is None or scope.user_id != self._current_user_id():
            raise RuntimeError("canvas deployment requires the current Runtime workspace")
        source = self.workspace_root / task["published_path"] if task["status"] == "published" else self._task_root(task_id)
        digest = self._tree_digest(source, self._manifest(task))
        if digest != task.get("validated_digest"):
            raise ValueError("canvas changed after validation")
        handle = runtime.workspace_service.resolve_workspace_handle(user_id=scope.user_id, workspace_id="_canvas_library" if reusable else scope.workspace_id)
        environment_id = f"env_{uuid.uuid4().hex}"
        relative = f".canvas_apps/{environment_id}"
        target = Path(handle.root_path) / relative
        target.mkdir(parents=True, exist_ok=False)
        for path in artifact_files(source):
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        if self._tree_digest(target, self._manifest(task)) != digest:
            raise ValueError("canvas changed during deployment")
        with bind_workspace(handle, scope.execution):
            result = await runtime.execute_computer_action("environment", "register", {
                "environment_id": environment_id, "name": task["description"], "root": relative,
                "entrypoint": task["canvas"]["entrypoint"], "lifetime": "reusable" if reusable else "session",
            })
        if not result.success:
            raise RuntimeError(result.error)
        return {"ok": True, "workspace_id": handle.workspace_id, **result.result}

    async def evolve_publish(self, task_id: str) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        if task.get("status") != "validated":
            raise ValueError("capability must pass validation before publishing")
        source_root = self._task_root(task_id)
        manifest = self._manifest(task)
        digest = self._tree_digest(source_root, manifest)
        if digest != task.get("validated_digest"):
            raise ValueError("capability changed after validation; validate it again before publishing")
        service_name = self._service_name(task)
        publish_root = self.staging_root.parent / "canvas-packages" if task.get("canvas") else self.publish_root
        publish_root.mkdir(parents=True, exist_ok=True)
        destination = (publish_root / service_name).resolve()
        try:
            destination.relative_to(publish_root.resolve())
        except ValueError as exc:
            raise PermissionError("capability publish path escaped generated extension root") from exc
        if destination.exists():
            marker = destination / ".published.json"
            existing = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
            if existing.get("digest") != digest:
                raise FileExistsError("this capability version already exists with different content; publish a new version")
        else:
            temporary = publish_root / f".{service_name}.{uuid.uuid4().hex}.tmp"
            try:
                temporary.mkdir(parents=False, exist_ok=False)
                for path in source_root.rglob("*"):
                    if not path.is_file() or path.name in _RESERVED_FILES:
                        continue
                    if path.is_symlink():
                        raise PermissionError("capability packages cannot contain symbolic links")
                    relative = path.relative_to(source_root)
                    target = temporary / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                if self._tree_digest(temporary, manifest) != digest:
                    raise RuntimeError("capability content changed while it was being published")
                (temporary / "agent-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (temporary / ".published.json").write_text(
                    json.dumps(
                        {"task_id": task_id, "digest": digest, "published_at": time.time()},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                temporary.rename(destination)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)

        if not task.get("canvas") and not callable(self._extension_reloader):
            raise RuntimeError("capability registry reload is not configured")
        registered = [] if task.get("canvas") else self._extension_reloader(
            [str(self.workspace_root / "extensions" / "community")],
            reload_modules=True,
        )
        registered_service = any(tool_id.startswith(f"{service_name}.") for tool_id in registered)
        if not task.get("canvas") and not registered_service:
            raise RuntimeError(f"published capability failed to register: {service_name}")

        def _record(row: Dict[str, Any]) -> None:
            row["status"] = "published"
            row["service_name"] = service_name
            row["package_digest"] = digest
            row["published_path"] = destination.relative_to(self.workspace_root).as_posix()
            row["published_at"] = time.time()

        published = self._update_task(task_id, _record)
        return {
            "ok": True,
            "task_id": task_id,
            "service_name": service_name,
            "tool_ids": [f"{service_name}.{row['command']}" for row in task["commands"]],
            "package_digest": digest,
            "registered": registered_service,
            "task": published,
        }
