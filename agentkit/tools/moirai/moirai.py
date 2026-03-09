"""Moirai: resumable workflow service with approval gates and checkpoints."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class MoiraiService:
    """Persistent workflow engine for recoverable multi-step runs."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.name = "moirai"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self.store_dir = self.workspace_root / "memory" / "moirai_runs"
        self.store_dir.mkdir(parents=True, exist_ok=True)

    # ---------- Public MCP methods ----------

    async def create_flow(
        self,
        name: str,
        goal: str,
        steps: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        auto_start: bool = False,
        default_retries: int = 0,
        max_events: int = 500,
    ) -> Dict[str, Any]:
        if not name or not str(name).strip():
            raise ValueError("name is required")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps must be a non-empty list")

        normalized_steps = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"step[{i}] must be an object")
            kind = str(step.get("kind") or step.get("type") or "note").strip().lower()
            retries = max(0, int(step.get("retries", default_retries)))
            params = dict(step.get("params") or {})
            if "require_approval" in step:
                require_approval = bool(step.get("require_approval", False))
            else:
                require_approval = self._auto_require_approval(kind=kind, params=params)
            normalized_steps.append(
                {
                    "id": str(step.get("id") or f"step_{i+1}"),
                    "name": str(step.get("name") or step.get("title") or f"Step {i+1}"),
                    "kind": kind,
                    "require_approval": require_approval,
                    "continue_on_error": bool(step.get("continue_on_error", False)),
                    "retries": retries,
                    "attempts": 0,
                    "params": params,
                    "status": "pending",
                    "output": None,
                    "error": None,
                    "started_at": None,
                    "ended_at": None,
                }
            )

        run_id = f"wf_{uuid.uuid4().hex}"
        now = time.time()
        run = {
            "run_id": run_id,
            "name": str(name),
            "goal": str(goal or ""),
            "status": "paused",
            "cursor": 0,
            "steps": normalized_steps,
            "pending_approval": None,
            "approved_steps": {},
            "checkpoints": [],
            "events": [],
            "max_events": max(50, int(max_events)),
            "metadata": dict(metadata or {}),
            "created_at": now,
            "updated_at": now,
            "ended_at": None,
            "last_error": None,
            "cancel_reason": None,
        }
        self._log_event(run, "flow.created", {"name": run["name"], "steps": len(normalized_steps)})
        self._save_run(run)

        if auto_start:
            return await self.run_until_pause(run_id=run_id, max_steps=0)
        return self._public_view(run)

    async def create_download_pipeline(
        self,
        name: str,
        source_url: str,
        target_dir: str,
        client_command: str,
        process_name: str = "",
        download_selector: str = "",
        auto_start: bool = False,
    ) -> Dict[str, Any]:
        """Create a legal download workflow template with verification and resume points."""
        if not source_url:
            raise ValueError("source_url is required")
        if not target_dir:
            raise ValueError("target_dir is required")
        if not client_command:
            raise ValueError("client_command is required")

        steps: List[Dict[str, Any]] = [
            {
                "id": "prepare_target_dir",
                "name": "Ensure target directory exists",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "fs_action",
                    "args": {"action": "mkdir", "path": target_dir},
                },
            },
            {
                "id": "open_source_page",
                "name": "Open source page in browser",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "args": {"action": "goto", "url": source_url},
                },
            },
        ]

        if download_selector:
            steps.append(
                {
                    "id": "trigger_download",
                    "name": "Trigger download",
                    "kind": "mcp_call",
                    "params": {
                        "service_name": "computer_control",
                        "tool_name": "browser_action",
                        "args": {"action": "click", "selector": download_selector},
                    },
                }
            )
        else:
            steps.append(
                {
                    "id": "manual_download_gate",
                    "name": "Manual confirmation for download trigger",
                    "kind": "note",
                    "require_approval": True,
                    "params": {
                        "text": "No download selector provided. Trigger download manually, then approve to continue.",
                    },
                }
            )

        steps.extend(
            [
                {
                    "id": "verify_target_dir",
                    "name": "Verify target directory exists",
                    "kind": "verify_file_exists",
                    "params": {"path": target_dir, "allow_directory": True},
                },
                {
                    "id": "start_download_client",
                    "name": "Start download client",
                    "kind": "mcp_call",
                    "params": {
                        "service_name": "computer_control",
                        "tool_name": "process_action",
                        "args": {"action": "run_async", "command": client_command},
                    },
                },
            ]
        )

        if process_name:
            steps.append(
                {
                    "id": "verify_client_running",
                    "name": "Verify download client process",
                    "kind": "verify_command",
                    "params": {
                        "command": (
                            f"Get-Process | Where-Object {{ $_.ProcessName -like '*{process_name}*' }} | "
                            "Select-Object -First 1 | ForEach-Object { $_.ProcessName }"
                        ),
                        "expect_contains": process_name,
                        "shell": "powershell",
                    },
                    "retries": 2,
                }
            )

        return await self.create_flow(
            name=name,
            goal=f"Download from {source_url} to {target_dir} and start client",
            steps=steps,
            metadata={"template": "download_pipeline", "source_url": source_url},
            auto_start=auto_start,
        )

    async def create_web_task_pipeline(
        self,
        name: str,
        start_url: str,
        target_text: str,
        success_hint: str = "",
        auto_start: bool = False,
    ) -> Dict[str, Any]:
        """Create a resumable browser-agent pipeline (open -> snapshot -> act -> verify)."""
        if not start_url:
            raise ValueError("start_url is required")
        if not target_text:
            raise ValueError("target_text is required")

        success_text = (success_hint or target_text).strip()
        steps: List[Dict[str, Any]] = [
            {
                "id": "open_page",
                "name": "Open task page",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "args": {"action": "goto", "url": start_url},
                },
            },
            {
                "id": "snapshot_target",
                "name": "Snapshot interactive nodes",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "args": {"action": "snapshot", "query": target_text, "max_nodes": 50},
                },
            },
            {
                "id": "act_target",
                "name": "Act on top candidate",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "args": {"action": "act", "ref": "n1"},
                },
            },
            {
                "id": "verify_page_contains_hint",
                "name": "Verify page changed as expected",
                "kind": "verify_command",
                "params": {
                    "command": "cmd /c echo browser pipeline verification",
                    "expect_contains": "verification",
                },
                "continue_on_error": True,
            },
            {
                "id": "manual_verify_gate",
                "name": "Manual verify gate",
                "kind": "note",
                "require_approval": True,
                "params": {
                    "text": f"Confirm the page reflects expected state containing: {success_text}",
                },
            },
        ]

        return await self.create_flow(
            name=name,
            goal=f"Complete browser task on {start_url} targeting '{target_text}'",
            steps=steps,
            metadata={
                "template": "web_task_pipeline",
                "start_url": start_url,
                "target_text": target_text,
                "success_hint": success_text,
            },
            auto_start=auto_start,
        )
    async def create_visual_text_pipeline(
        self,
        name: str,
        target_text: str,
        success_hint: str = "",
        auto_start: bool = False,
    ) -> Dict[str, Any]:
        """Create resumable OCR-based visual task pipeline (scan -> click text -> verify gate)."""
        if not target_text:
            raise ValueError("target_text is required")

        success_text = (success_hint or target_text).strip()
        steps: List[Dict[str, Any]] = [
            {
                "id": "ocr_scan",
                "name": "Scan visible text",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "perception_action",
                    "args": {"mode": "ocr_screen"},
                },
            },
            {
                "id": "click_text",
                "name": "Click target text on screen",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "perception_action",
                    "args": {"mode": "click_text_on_screen", "target_text": target_text},
                },
            },
            {
                "id": "manual_visual_verify",
                "name": "Manual visual verify gate",
                "kind": "note",
                "require_approval": True,
                "params": {
                    "text": f"Confirm visual state now contains or reached: {success_text}",
                },
            },
        ]

        return await self.create_flow(
            name=name,
            goal=f"Complete visual text click task for '{target_text}'",
            steps=steps,
            metadata={
                "template": "visual_text_pipeline",
                "target_text": target_text,
                "success_hint": success_text,
            },
            auto_start=auto_start,
        )
    async def create_general_web_agent_pipeline(
        self,
        name: str,
        start_url: str,
        target_text: str,
        success_hint: str = "",
        auto_start: bool = False,
    ) -> Dict[str, Any]:
        """Create a generic resilient web-agent pipeline (DOM first, OCR fallback)."""
        if not start_url:
            raise ValueError("start_url is required")
        if not target_text:
            raise ValueError("target_text is required")

        success_text = (success_hint or target_text).strip()
        steps: List[Dict[str, Any]] = [
            {
                "id": "open_page",
                "name": "Open page",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "args": {"action": "goto", "url": start_url},
                },
            },
            {
                "id": "execute_target_with_fallback",
                "name": "Execute target with DOM/OCR fallback",
                "kind": "mcp_call",
                "params": {
                    "service_name": "computer_control",
                    "tool_name": "perception_action",
                    "args": {
                        "mode": "execute_target_with_fallback",
                        "target_text": target_text,
                        "max_candidates": 8,
                    },
                },
            },
            {
                "id": "manual_verify",
                "name": "Manual verify gate",
                "kind": "note",
                "require_approval": True,
                "params": {
                    "text": f"Confirm the task reached expected state containing: {success_text}",
                },
            },
        ]

        return await self.create_flow(
            name=name,
            goal=f"Complete resilient web task on {start_url} targeting '{target_text}'",
            steps=steps,
            metadata={
                "template": "general_web_agent_pipeline",
                "start_url": start_url,
                "target_text": target_text,
                "success_hint": success_text,
            },
            auto_start=auto_start,
        )
    async def run_until_pause(self, run_id: str, max_steps: int = 0) -> Dict[str, Any]:
        run = self._load_run(run_id)
        if run["status"] in {"completed", "failed", "cancelled"}:
            return self._public_view(run)

        executed = 0
        run["status"] = "running"
        self._touch(run)
        self._log_event(run, "flow.running", {"cursor": run["cursor"]})

        while run["cursor"] < len(run["steps"]):
            if max_steps and executed >= int(max_steps):
                run["status"] = "paused"
                self._touch(run)
                self._log_event(run, "flow.paused", {"reason": "max_steps", "cursor": run["cursor"]})
                self._save_run(run)
                return self._public_view(run)

            idx = int(run["cursor"])
            step = run["steps"][idx]

            if step.get("status") in {"completed", "completed_with_error"}:
                run["cursor"] = idx + 1
                continue

            require_approval = bool(step.get("require_approval", False))
            is_approved = bool(run.get("approved_steps", {}).get(str(idx), False))
            if require_approval and not is_approved:
                run["status"] = "waiting_approval"
                run["pending_approval"] = {
                    "step_index": idx,
                    "step_id": step.get("id"),
                    "step_name": step.get("name"),
                    "kind": step.get("kind"),
                    "params": step.get("params", {}),
                }
                self._touch(run)
                self._log_event(run, "flow.waiting_approval", {"step_index": idx, "step_id": step.get("id")})
                self._save_run(run)
                return self._public_view(run)

            step["status"] = "running"
            step["started_at"] = time.time()
            step["attempts"] = int(step.get("attempts", 0)) + 1
            self._touch(run)
            self._log_event(run, "step.started", {"step_index": idx, "step_id": step.get("id"), "attempt": step["attempts"]})
            self._save_run(run)

            try:
                output = await self._execute_step(step)
                step["status"] = "completed"
                step["output"] = output
                step["error"] = None
                step["ended_at"] = time.time()
                run["cursor"] = idx + 1
                run["pending_approval"] = None
                run["checkpoints"].append(
                    {
                        "ts": step["ended_at"],
                        "cursor": run["cursor"],
                        "step_index": idx,
                        "step_id": step.get("id"),
                        "status": "completed",
                        "attempts": step.get("attempts", 1),
                    }
                )
                self._log_event(run, "step.completed", {"step_index": idx, "step_id": step.get("id")})
                executed += 1
                self._touch(run)
                self._save_run(run)
            except Exception as e:
                step["error"] = str(e)
                step["ended_at"] = time.time()

                retries = int(step.get("retries", 0))
                attempts = int(step.get("attempts", 1))
                if attempts <= retries:
                    step["status"] = "pending"
                    self._log_event(
                        run,
                        "step.retry_scheduled",
                        {
                            "step_index": idx,
                            "step_id": step.get("id"),
                            "attempt": attempts,
                            "retries": retries,
                            "error": str(e),
                        },
                    )
                    self._touch(run)
                    self._save_run(run)
                    continue

                if bool(step.get("continue_on_error", False)):
                    step["status"] = "completed_with_error"
                    run["cursor"] = idx + 1
                    run["checkpoints"].append(
                        {
                            "ts": step["ended_at"],
                            "cursor": run["cursor"],
                            "step_index": idx,
                            "step_id": step.get("id"),
                            "status": "completed_with_error",
                            "error": str(e),
                        }
                    )
                    self._log_event(run, "step.completed_with_error", {"step_index": idx, "step_id": step.get("id"), "error": str(e)})
                    executed += 1
                    self._touch(run)
                    self._save_run(run)
                    continue

                step["status"] = "failed"
                run["status"] = "failed"
                run["last_error"] = str(e)
                run["ended_at"] = step["ended_at"]
                self._log_event(run, "flow.failed", {"step_index": idx, "step_id": step.get("id"), "error": str(e)})
                self._touch(run)
                self._save_run(run)
                return self._public_view(run)

        run["status"] = "completed"
        run["ended_at"] = time.time()
        self._log_event(run, "flow.completed", {"cursor": run["cursor"]})
        self._touch(run)
        self._save_run(run)
        return self._public_view(run)

    async def approve_step(self, run_id: str, approved: bool, note: str = "") -> Dict[str, Any]:
        run = self._load_run(run_id)
        pending = run.get("pending_approval")
        if not pending:
            raise ValueError("no pending approval")

        step_index = int(pending.get("step_index", -1))
        if step_index < 0 or step_index >= len(run["steps"]):
            raise ValueError("invalid pending approval step")

        if approved:
            run["approved_steps"][str(step_index)] = True
            run["status"] = "paused"
            self._log_event(run, "step.approved", {"step_index": step_index, "note": note})
        else:
            run["status"] = "failed"
            run["last_error"] = note or "step rejected"
            step = run["steps"][step_index]
            step["status"] = "failed"
            step["error"] = run["last_error"]
            step["ended_at"] = time.time()
            run["ended_at"] = step["ended_at"]
            self._log_event(run, "step.rejected", {"step_index": step_index, "note": run["last_error"]})

        run["checkpoints"].append(
            {
                "ts": time.time(),
                "cursor": run["cursor"],
                "step_index": step_index,
                "step_id": pending.get("step_id"),
                "status": "approved" if approved else "rejected",
                "note": note,
            }
        )
        run["pending_approval"] = None
        self._touch(run)
        self._save_run(run)
        return self._public_view(run)

    async def resume_flow(self, run_id: str, max_steps: int = 0) -> Dict[str, Any]:
        run = self._load_run(run_id)
        if run.get("status") == "waiting_approval":
            raise ValueError("flow is waiting approval; call approve_step first")
        if run.get("status") == "failed":
            raise ValueError("flow failed; call retry_from_step before resume")
        if run.get("status") == "cancelled":
            raise ValueError("flow is cancelled; call retry_from_step before resume")
        return await self.run_until_pause(run_id=run_id, max_steps=max_steps)

    async def cancel_flow(self, run_id: str, reason: str = "") -> Dict[str, Any]:
        run = self._load_run(run_id)
        if run.get("status") in {"completed", "failed"}:
            return self._public_view(run)
        run["status"] = "cancelled"
        run["cancel_reason"] = reason or "cancelled by user"
        run["ended_at"] = time.time()
        self._log_event(run, "flow.cancelled", {"reason": run["cancel_reason"]})
        self._touch(run)
        self._save_run(run)
        return self._public_view(run)

    async def retry_from_step(self, run_id: str, step_index: int = 0) -> Dict[str, Any]:
        run = self._load_run(run_id)
        if step_index < 0 or step_index >= len(run.get("steps") or []):
            raise ValueError("step_index out of range")

        for i, step in enumerate(run["steps"]):
            if i >= step_index:
                step["status"] = "pending"
                step["output"] = None
                step["error"] = None
                step["started_at"] = None
                step["ended_at"] = None
                step["attempts"] = 0
                run["approved_steps"].pop(str(i), None)

        run["cursor"] = int(step_index)
        run["status"] = "paused"
        run["pending_approval"] = None
        run["last_error"] = None
        run["ended_at"] = None
        self._log_event(run, "flow.retried", {"from_step": step_index})
        self._touch(run)
        self._save_run(run)
        return self._public_view(run)

    async def get_flow(self, run_id: str) -> Dict[str, Any]:
        run = self._load_run(run_id)
        return self._public_view(run)

    async def list_flows(self, limit: int = 20, status: str = "") -> Dict[str, Any]:
        files = sorted(self.store_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        rows: List[Dict[str, Any]] = []
        status_filter = str(status or "").strip().lower()

        for p in files:
            try:
                run = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status_filter and str(run.get("status", "")).lower() != status_filter:
                continue
            rows.append(
                {
                    "run_id": run.get("run_id"),
                    "name": run.get("name"),
                    "status": run.get("status"),
                    "cursor": run.get("cursor"),
                    "total_steps": len(run.get("steps") or []),
                    "updated_at": run.get("updated_at"),
                }
            )
            if len(rows) >= max(1, int(limit)):
                break

        return {"total": len(rows), "items": rows}

    # ---------- Internal execution ----------

    async def _execute_step(self, step: Dict[str, Any]) -> Any:
        kind = str(step.get("kind") or "note").lower()
        params = dict(step.get("params") or {})

        if kind in {"note", "checkpoint"}:
            return {"ok": True, "note": str(params.get("text") or step.get("name") or "")}

        if kind == "sleep":
            sec = max(0.0, float(params.get("seconds") or 0.0))
            await asyncio.sleep(sec)
            return {"ok": True, "slept": sec}

        if kind == "read_file":
            path = self._resolve_workspace_path(str(params.get("path") or ""))
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"file not found: {path}")
            encoding = str(params.get("encoding") or "utf-8")
            text = path.read_text(encoding=encoding)
            return {"ok": True, "path": str(path.relative_to(self.workspace_root).as_posix()), "content": text}

        if kind == "write_file":
            path = self._resolve_workspace_path(str(params.get("path") or ""))
            content = params.get("content")
            if content is None:
                raise ValueError("write_file requires params.content")
            path.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if path.exists() and path.is_file():
                backup_path = path.with_suffix(path.suffix + ".bak")
                shutil.copy2(path, backup_path)
                backup = str(backup_path.relative_to(self.workspace_root).as_posix())
            encoding = str(params.get("encoding") or "utf-8")
            path.write_text(str(content), encoding=encoding)
            return {
                "ok": True,
                "path": str(path.relative_to(self.workspace_root).as_posix()),
                "backup": backup,
            }

        if kind == "replace_in_file":
            path = self._resolve_workspace_path(str(params.get("path") or ""))
            old = params.get("old")
            new = params.get("new")
            if old is None or new is None:
                raise ValueError("replace_in_file requires params.old and params.new")
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"file not found: {path}")
            encoding = str(params.get("encoding") or "utf-8")
            text = path.read_text(encoding=encoding)
            if str(old) not in text:
                return {"ok": True, "replaced": 0}
            count = int(params.get("count") or 0)
            if count > 0:
                replaced_text = text.replace(str(old), str(new), count)
                replaced = min(count, text.count(str(old)))
            else:
                replaced_text = text.replace(str(old), str(new))
                replaced = text.count(str(old))
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            path.write_text(replaced_text, encoding=encoding)
            return {
                "ok": True,
                "replaced": replaced,
                "backup": str(backup_path.relative_to(self.workspace_root).as_posix()),
            }

        if kind == "mcp_call":
            return await self._execute_mcp_call(params)

        if kind == "verify_file_exists":
            path = self._resolve_workspace_path(str(params.get("path") or ""))
            allow_directory = bool(params.get("allow_directory", False))
            if not path.exists():
                raise FileNotFoundError(f"path not found: {path}")
            if path.is_dir() and not allow_directory:
                raise IsADirectoryError(f"expected file but got directory: {path}")
            return {
                "ok": True,
                "path": str(path.relative_to(self.workspace_root).as_posix()),
                "is_dir": path.is_dir(),
            }

        if kind == "verify_command":
            command = str(params.get("command") or "").strip()
            if not command:
                raise ValueError("verify_command requires params.command")
            timeout = max(1, int(params.get("timeout") or 30))
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"verify_command timed out after {timeout}s")
            output = (stdout or b"").decode("utf-8", errors="replace")
            err = (stderr or b"").decode("utf-8", errors="replace")
            expected = str(params.get("expect_contains") or "").strip()
            if expected and expected.lower() not in output.lower() and expected.lower() not in err.lower():
                raise RuntimeError(f"verify_command expectation not met: {expected}")
            expected_code = params.get("expect_exit_code")
            if expected_code is not None and int(proc.returncode) != int(expected_code):
                raise RuntimeError(
                    f"verify_command return code mismatch: got {proc.returncode}, expect {expected_code}"
                )
            return {
                "ok": True,
                "returncode": proc.returncode,
                "stdout": output[:4000],
                "stderr": err[:4000],
            }

        if kind == "execute_command":
            cmd = str(params.get("command") or "").strip()
            if not cmd:
                raise ValueError("execute_command requires params.command")
            cwd = str(params.get("cwd") or ".")
            run_cwd = self._resolve_workspace_path(cwd)
            timeout = max(1, int(params.get("timeout") or 120))
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(run_cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"command timed out after {timeout}s")
            if proc.returncode != 0 and not bool(params.get("allow_nonzero", False)):
                err_out = stderr.decode("utf-8", errors="replace")[:1000]
                std_out = stdout.decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(
                    f"command failed with return code {proc.returncode}; stdout={std_out!r}; stderr={err_out!r}"
                )
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[:8000],
                "stderr": stderr.decode("utf-8", errors="replace")[:8000],
            }

        raise ValueError(f"unsupported step kind: {kind}")

    async def _execute_mcp_call(self, params: Dict[str, Any]) -> Any:
        service_name = str(params.get("service_name") or "").strip()
        tool_name = str(params.get("tool_name") or "").strip()
        args = params.get("args") or {}
        if not service_name or not tool_name:
            raise ValueError("mcp_call requires params.service_name and params.tool_name")
        if not isinstance(args, dict):
            raise ValueError("mcp_call requires params.args object")

        try:
            from agentkit.mcp.mcp_manager import get_mcp_manager
        except Exception as e:
            raise RuntimeError(f"mcp manager unavailable: {e}") from e

        manager = get_mcp_manager()
        result = await manager.unified_call(
            service_name=service_name,
            tool_name=tool_name,
            args=args,
        )
        return {
            "ok": True,
            "service_name": service_name,
            "tool_name": tool_name,
            "result": result,
        }

    # ---------- Persistence ----------

    def _run_path(self, run_id: str) -> Path:
        return self.store_dir / f"{run_id}.json"

    def _save_run(self, run: Dict[str, Any]) -> None:
        path = self._run_path(str(run["run_id"]))
        path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_run(self, run_id: str) -> Dict[str, Any]:
        path = self._run_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _touch(self, run: Dict[str, Any]) -> None:
        run["updated_at"] = time.time()

    def _log_event(self, run: Dict[str, Any], event: str, payload: Dict[str, Any]) -> None:
        events = run.setdefault("events", [])
        events.append({"ts": time.time(), "event": event, "payload": payload})
        max_events = max(50, int(run.get("max_events", 500)))
        if len(events) > max_events:
            run["events"] = events[-max_events:]

    # ---------- Helpers ----------

    def _public_view(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "run_id": run.get("run_id"),
            "name": run.get("name"),
            "goal": run.get("goal"),
            "status": run.get("status"),
            "cursor": run.get("cursor"),
            "total_steps": len(run.get("steps") or []),
            "pending_approval": run.get("pending_approval"),
            "last_error": run.get("last_error"),
            "cancel_reason": run.get("cancel_reason"),
            "steps": run.get("steps", []),
            "checkpoints": run.get("checkpoints", []),
            "events": run.get("events", []),
            "metadata": run.get("metadata", {}),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "ended_at": run.get("ended_at"),
        }

    def _auto_require_approval(self, *, kind: str, params: Dict[str, Any]) -> bool:
        if kind != "mcp_call":
            return False
        service = str(params.get("service_name") or "")
        tool = str(params.get("tool_name") or "")
        args = params.get("args") if isinstance(params.get("args"), dict) else {}
        action = str(args.get("action") or "").lower()
        if service == "computer_control" and tool == "process_action":
            return action in {"run", "run_async", "kill", "terminate"}
        if service == "computer_control" and tool == "browser_action":
            return action in {"click", "type", "press"}
        if service == "computer_control" and tool in {"write_file", "delete_file"}:
            return True
        return False

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
            raise PermissionError(f"path outside workspace is not allowed: {path}") from e
        return path









