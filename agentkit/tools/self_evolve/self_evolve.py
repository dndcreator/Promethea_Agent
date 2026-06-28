"""Self-evolution service focused on controlled agent code evolution workflows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentkit.security.sandbox import get_sandbox_policy

SELF_MODEL_DOCS = [
    "docs/runtime-overview.md",
    "docs/architecture/runtime-io.md",
    "docs/architecture/tool-runtime.md",
    "docs/architecture/memory-model.md",
    "docs/architecture/conversation-pipeline.md",
    "docs/ui-overview.md",
]


class SelfEvolveService:
    """Specialized service for self-improvement planning, patching, and validation."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.name = "self_evolve"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_path = self.workspace_root / "memory" / "self_evolve_tasks.json"
        self.self_model_path = self.workspace_root / "memory" / "self_model.json"
        self._sandbox = get_sandbox_policy()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _resolve_workspace_path(self, path_str: str) -> Path:
        if not path_str:
            raise ValueError("path is required")
        path = Path(path_str)
        if not path.is_absolute():
            path = self.workspace_root / path
        path = path.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as e:
            raise PermissionError(f"Path outside workspace is not allowed: {path}") from e
        return path

    def _load_tasks(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return {"tasks": {}}
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("tasks"), dict):
                return raw
            return {"tasks": {}}
        except Exception:
            return {"tasks": {}}

    def _save_tasks(self, state: Dict[str, Any]) -> None:
        self.store_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _doc_outline(text: str, *, max_lines: int = 80) -> List[str]:
        lines: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("- `") or line.startswith("- "):
                lines.append(line)
            if len(lines) >= max_lines:
                break
        return lines

    def _read_self_model_docs(self, *, max_chars_per_file: int) -> List[Dict[str, Any]]:
        docs: List[Dict[str, Any]] = []
        cap = max(500, int(max_chars_per_file))
        for rel in SELF_MODEL_DOCS:
            path = self._resolve_workspace_path(rel)
            if not path.exists() or not path.is_file():
                docs.append({"path": rel, "exists": False, "sha256": "", "outline": []})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                {
                    "path": rel,
                    "exists": True,
                    "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                    "outline": self._doc_outline(text[:cap]),
                }
            )
        return docs

    @staticmethod
    def _build_capability_inventory() -> Dict[str, Any]:
        return {
            "conversation_runtime": {
                "status": "documented",
                "modules": ["ConversationService", "RuntimeBlock", "ContextCompiler", "PromptAssembler"],
                "role": "compile user input, context, memory, tools, reasoning, and workflow outputs into LLM turns",
            },
            "memory": {
                "status": "documented",
                "modules": ["MemoryService", "memory recall", "memory write gate"],
                "role": "controlled recall and durable memory writes through runtime services",
            },
            "reasoning": {
                "status": "documented",
                "modules": ["PromptPolicyRouter", "ReasoningService", "reasoning tree"],
                "role": "route complex work into explicit multi-step reasoning with summaries and traces",
            },
            "tools": {
                "status": "documented",
                "modules": ["ToolService", "ToolRegistry", "ToolPolicy"],
                "role": "normalize, govern, execute, and observe local/MCP/community tools",
            },
            "workflow": {
                "status": "documented",
                "modules": ["workflow engine", "recovery/checkpoint surfaces"],
                "role": "long-running or recoverable task orchestration when enabled",
            },
            "self_evolve": {
                "status": "active",
                "modules": ["SelfEvolveService", "self_model", "task context", "patch", "validate"],
                "role": "maintain a self-knowledge baseline and run controlled improvement tasks",
            },
        }

    @staticmethod
    def _build_architecture_map() -> Dict[str, Any]:
        return {
            "single_turn_path": [
                "input normalization",
                "runtime context construction",
                "prompt policy routing",
                "memory recall when budgeted",
                "direct/light_action/deep_reasoning/workflow execution",
                "response synthesis",
                "memory write review",
            ],
            "key_boundaries": {
                "ConversationService": "LLM I/O hub, not owner of memory/tools/reasoning/workflows",
                "MemoryService": "memory recall and write decisions",
                "ReasoningService": "reasoning trees and summaries",
                "ToolService": "tool registry, policy, execution, observations",
                "SelfEvolveService": "self model, controlled code task lifecycle, validation",
            },
            "artifact_flow": {
                "docs": "source of lightweight self-model facts",
                "memory/self_model.json": "persisted self-evolution baseline",
                "self_evolve_tasks.json": "reviewable evolution task log",
            },
        }

    @staticmethod
    def _build_runtime_boundaries() -> List[str]:
        return [
            "Do not claim live code/file/tool inspection unless the current turn contains an observation.",
            "Treat the self model as a docs-derived baseline, not direct runtime introspection.",
            "Refresh or mark the self model stale when source docs change.",
            "Self-evolve tasks should identify the affected module before proposing a patch.",
            "Core code changes remain controlled and reviewable; self-evolve should not silently modify arbitrary files.",
        ]

    @staticmethod
    def _build_improvement_backlog() -> List[Dict[str, str]]:
        return [
            {
                "area": "self_model_freshness",
                "priority": "high",
                "proposal": "Compare source doc hashes before self-evolve work and refresh stale self models.",
            },
            {
                "area": "architecture_grounding",
                "priority": "high",
                "proposal": "Use the self model as a required baseline for self-evolve planning and require code/tool claims to cite observations.",
            },
            {
                "area": "task_planning",
                "priority": "medium",
                "proposal": "Attach affected modules and acceptance criteria to each self-evolve task.",
            },
            {
                "area": "capability_inventory",
                "priority": "medium",
                "proposal": "Extend the self model from docs-only inventory to registry-backed tools and runtime service snapshots.",
            },
            {
                "area": "drift_detection",
                "priority": "medium",
                "proposal": "Diff old and new self models to produce migration notes and suggested tests.",
            },
            {
                "area": "general_agent_readiness",
                "priority": "medium",
                "proposal": "Track whether memory, tools, reasoning, workflows, UI interruption, and validation are actually wired end to end.",
            },
        ]

    @classmethod
    def _build_self_model_summary(cls, docs: List[Dict[str, Any]]) -> str:
        available = [str(doc.get("path")) for doc in docs if doc.get("exists")]
        capabilities = ", ".join(cls._build_capability_inventory().keys())
        return "\n".join(
            [
                "Promethea self model, derived from repository architecture docs.",
                "Known runtime structure:",
                "- Promethea is a runtime, not only a prompt-wrapped base model.",
                "- The request path coordinates identity, runtime context, prompt policy routing, memory, reasoning, tools, workflows, and safety boundaries.",
                "- ConversationService is the LLM I/O hub; it compiles RuntimeBlock inputs and calls the active model.",
                "- Prompt policy routing chooses direct, light_action, deep_reasoning, or workflow budgets before final answer generation.",
                "- ReasoningService owns reasoning trees and summaries for multi-step work.",
                "- MemoryService owns recall and memory-write decisions; memory is available through controlled runtime paths, not direct model introspection.",
                "- ToolService owns tool registry, normalization, policy checks, execution, and observations.",
                "- Self-evolve provides controlled code-evolution tasks, context collection, patching, validation, and this docs-derived self model.",
                f"Capability inventory areas: {capabilities}.",
                "Boundaries:",
                "- The assistant must not claim it inspected code, called tools, read files, or checked live runtime state unless the current turn contains an actual observation/result.",
                "- This self model is a docs-derived architecture snapshot and may be stale after code changes.",
                f"Source docs: {', '.join(available) if available else 'none'}",
            ]
        )

    def _self_model_freshness(self, model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if model is None:
            if not self.self_model_path.exists():
                return {"exists": False, "stale": True, "changed_sources": [], "missing_sources": SELF_MODEL_DOCS}
            try:
                model = json.loads(self.self_model_path.read_text(encoding="utf-8"))
            except Exception:
                return {"exists": True, "stale": True, "changed_sources": ["memory/self_model.json"], "missing_sources": []}
        docs_now = self._read_self_model_docs(max_chars_per_file=500)
        previous_docs = model.get("documents") if isinstance(model.get("documents"), list) else []
        previous_by_path = {str(doc.get("path")): doc for doc in previous_docs if isinstance(doc, dict)}
        changed: List[str] = []
        missing: List[str] = []
        for doc in docs_now:
            rel = str(doc.get("path") or "")
            if not doc.get("exists"):
                missing.append(rel)
                continue
            old = previous_by_path.get(rel) or {}
            if old.get("sha256") != doc.get("sha256"):
                changed.append(rel)
        return {
            "exists": True,
            "stale": bool(changed or missing),
            "changed_sources": changed,
            "missing_sources": missing,
        }

    async def evolve_build_self_model(self, max_chars_per_file: int = 5000) -> Dict[str, Any]:
        docs = self._read_self_model_docs(max_chars_per_file=max_chars_per_file)
        model = {
            "kind": "promethea_self_model",
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "self_evolve.docs",
            "summary": self._build_self_model_summary(docs),
            "architecture_map": self._build_architecture_map(),
            "capability_inventory": self._build_capability_inventory(),
            "runtime_boundaries": self._build_runtime_boundaries(),
            "improvement_backlog": self._build_improvement_backlog(),
            "documents": docs,
        }
        model["freshness"] = self._self_model_freshness(model)
        self.self_model_path.parent.mkdir(parents=True, exist_ok=True)
        self.self_model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "self_model": model, "path": self.self_model_path.relative_to(self.workspace_root).as_posix()}

    async def evolve_get_self_model(self) -> Dict[str, Any]:
        if not self.self_model_path.exists():
            return {"ok": True, "exists": False, "self_model": None, "path": self.self_model_path.relative_to(self.workspace_root).as_posix()}
        raw = json.loads(self.self_model_path.read_text(encoding="utf-8"))
        raw["freshness"] = self._self_model_freshness(raw)
        return {"ok": True, "exists": True, "self_model": raw, "path": self.self_model_path.relative_to(self.workspace_root).as_posix()}

    def _get_task_or_raise(self, task_id: str) -> Dict[str, Any]:
        state = self._load_tasks()
        task = state.get("tasks", {}).get(task_id)
        if not task:
            raise FileNotFoundError(f"task not found: {task_id}")
        return task

    def _update_task(self, task_id: str, updater) -> Dict[str, Any]:
        state = self._load_tasks()
        task = state.get("tasks", {}).get(task_id)
        if not task:
            raise FileNotFoundError(f"task not found: {task_id}")
        updater(task)
        task["updated_at"] = time.time()
        self._save_tasks(state)
        return task

    async def evolve_create_task(
        self,
        goal: str,
        target_files: List[str],
        acceptance_criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not goal or not str(goal).strip():
            raise ValueError("goal is required")
        if not isinstance(target_files, list) or not target_files:
            raise ValueError("target_files must be a non-empty list")

        normalized_files: List[str] = []
        for rel in target_files:
            p = self._resolve_workspace_path(str(rel))
            normalized_files.append(p.relative_to(self.workspace_root).as_posix())

        now = time.time()
        self_model_snapshot: Dict[str, Any] = {"exists": False}
        if self.self_model_path.exists():
            try:
                raw_self_model = json.loads(self.self_model_path.read_text(encoding="utf-8"))
                self_model_snapshot = {
                    "exists": True,
                    "version": raw_self_model.get("version"),
                    "generated_at": raw_self_model.get("generated_at"),
                    "freshness": self._self_model_freshness(raw_self_model),
                    "capability_areas": sorted((raw_self_model.get("capability_inventory") or {}).keys()),
                }
            except Exception:
                self_model_snapshot = {"exists": True, "error": "failed_to_read_self_model"}
        task_id = f"se_{uuid.uuid4().hex}"
        task = {
            "task_id": task_id,
            "goal": str(goal).strip(),
            "target_files": sorted(set(normalized_files)),
            "acceptance_criteria": [str(x) for x in (acceptance_criteria or []) if str(x).strip()],
            "status": "planned",
            "self_model_snapshot": self_model_snapshot,
            "changes": [],
            "validations": [],
            "created_at": now,
            "updated_at": now,
        }

        state = self._load_tasks()
        state.setdefault("tasks", {})[task_id] = task
        self._save_tasks(state)
        return {"ok": True, "task": task}

    async def evolve_get_task(self, task_id: str) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        return {"ok": True, "task": task}

    async def evolve_list_tasks(self, limit: int = 20, status: str = "") -> Dict[str, Any]:
        state = self._load_tasks()
        rows = list(state.get("tasks", {}).values())
        status_filter = str(status or "").strip().lower()
        if status_filter:
            rows = [x for x in rows if str(x.get("status", "")).lower() == status_filter]
        rows = sorted(rows, key=lambda x: float(x.get("updated_at", 0)), reverse=True)
        rows = rows[: max(1, int(limit))]
        return {"ok": True, "total": len(rows), "tasks": rows}

    async def evolve_collect_context(
        self,
        task_id: str,
        max_chars_per_file: int = 4000,
    ) -> Dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        out: List[Dict[str, Any]] = []
        cap = max(200, int(max_chars_per_file))
        self_model = await self.evolve_get_self_model()
        if self_model.get("exists") and isinstance(self_model.get("self_model"), dict):
            model = self_model["self_model"]
            context_model = {
                "summary": model.get("summary"),
                "architecture_map": model.get("architecture_map"),
                "capability_inventory": model.get("capability_inventory"),
                "runtime_boundaries": model.get("runtime_boundaries"),
                "improvement_backlog": model.get("improvement_backlog"),
                "freshness": model.get("freshness"),
            }
            out.append(
                {
                    "path": "memory/self_model.json",
                    "exists": True,
                    "role": "self_evolution_baseline",
                    "content": json.dumps(context_model, ensure_ascii=False, indent=2)[:cap],
                }
            )

        for rel in task.get("target_files", []):
            p = self._resolve_workspace_path(rel)
            if not p.exists() or not p.is_file():
                out.append({"path": rel, "exists": False, "content": ""})
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            out.append({"path": rel, "exists": True, "content": text[:cap]})

        return {
            "ok": True,
            "task_id": task_id,
            "goal": task.get("goal", ""),
            "context": out,
        }

    async def evolve_apply_patch(
        self,
        task_id: str,
        path: str,
        old: str,
        new: str,
        count: int = 1,
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        if not old:
            raise ValueError("old cannot be empty")

        task = self._get_task_or_raise(task_id)
        rel = self._resolve_workspace_path(path).relative_to(self.workspace_root).as_posix()
        allowed = set(task.get("target_files", []))
        if rel not in allowed:
            raise PermissionError(f"path not declared in task target_files: {rel}")

        file_path = self._resolve_workspace_path(rel)
        path_decision = self._sandbox.check_path(str(file_path), intent="patch", workspace_root=self.workspace_root)
        if not path_decision.allowed:
            raise PermissionError(f"sandbox blocked patch: {path_decision.reason}")
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        text = file_path.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            return {"ok": False, "task_id": task_id, "path": rel, "updated": False, "reason": "old text not found"}

        if create_backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)

        n = max(1, int(count))
        updated_text = text.replace(old, new, n)
        applied = min(n, text.count(old))
        file_path.write_text(updated_text, encoding="utf-8")

        def _append_change(t: Dict[str, Any]) -> None:
            t.setdefault("changes", []).append(
                {
                    "ts": time.time(),
                    "path": rel,
                    "op": "replace",
                    "count": applied,
                    "old_excerpt": old[:120],
                    "new_excerpt": str(new)[:120],
                }
            )
            if t.get("status") == "planned":
                t["status"] = "editing"

        self._update_task(task_id, _append_change)

        return {
            "ok": True,
            "task_id": task_id,
            "path": rel,
            "updated": True,
            "replaced": applied,
        }

    async def evolve_validate(
        self,
        task_id: str,
        command: str,
        cwd: str = ".",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        if not command or not str(command).strip():
            raise ValueError("command cannot be empty")

        self._get_task_or_raise(task_id)
        run_cwd = self._resolve_workspace_path(cwd)
        cmd_decision = self._sandbox.check_command(command, cwd=str(run_cwd), workspace_root=self.workspace_root)
        if not cmd_decision.allowed:
            raise PermissionError(f"sandbox blocked validate command: {cmd_decision.reason}")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(run_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=max(1, int(timeout))
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Validation timed out after {timeout}s")

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        ok = int(proc.returncode) == 0

        def _append_validation(t: Dict[str, Any]) -> None:
            t.setdefault("validations", []).append(
                {
                    "ts": time.time(),
                    "command": command,
                    "cwd": run_cwd.relative_to(self.workspace_root).as_posix(),
                    "returncode": int(proc.returncode),
                    "ok": ok,
                    "stdout": out[:4000],
                    "stderr": err[:4000],
                }
            )
            t["status"] = "validated" if ok else "failed_validation"

        self._update_task(task_id, _append_validation)

        return {
            "ok": ok,
            "task_id": task_id,
            "returncode": int(proc.returncode),
            "stdout": out[:4000],
            "stderr": err[:4000],
        }




