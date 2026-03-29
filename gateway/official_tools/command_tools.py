from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agentkit.security.sandbox import get_sandbox_policy
from gateway.tool_service import ToolInvocationContext


class RuntimeExecCommandTool:
    tool_id = "runtime.exec_command"
    name = "runtime.exec_command"
    description = "Execute a shell command under sandbox policy."
    official = True
    official_domain = "runtime"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        command = str((args or {}).get("command") or "").strip()
        if not command:
            raise ValueError("command is required")
        cwd = str((args or {}).get("cwd") or ".").strip() or "."
        timeout_s = int((args or {}).get("timeout_s") or 60)
        timeout_s = max(1, min(timeout_s, 600))

        decision = get_sandbox_policy().check_command(command, cwd=cwd)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked command: {decision.reason}")

        started = time.time()
        proc = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            shell=True,  # noqa: S602
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        max_chars = int((args or {}).get("max_output_chars") or 20000)
        max_chars = max(200, min(max_chars, 500000))
        return {
            "ok": proc.returncode == 0,
            "command": command,
            "cwd": str(Path(cwd).resolve()),
            "returncode": proc.returncode,
            "stdout": stdout[:max_chars],
            "stderr": stderr[:max_chars],
            "truncated_stdout": len(stdout) > max_chars,
            "truncated_stderr": len(stderr) > max_chars,
            "duration_ms": int((time.time() - started) * 1000),
            "session_id": (ctx.session_id if ctx else None),
            "user_id": (ctx.user_id if ctx else None),
        }


class RuntimeReadEnvTool:
    tool_id = "runtime.read_env"
    name = "runtime.read_env"
    description = "Read environment variables by allowlisted names or prefixes."
    official = True
    official_domain = "runtime"

    SENSITIVE_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")

    @staticmethod
    def _should_redact(key: str) -> bool:
        upper = str(key or "").upper()
        return any(x in upper for x in RuntimeReadEnvTool.SENSITIVE_FRAGMENTS)

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        names = (args or {}).get("names") or []
        prefixes = (args or {}).get("prefixes") or []
        include_empty = bool((args or {}).get("include_empty", False))
        redact_sensitive = bool((args or {}).get("redact_sensitive", True))
        if not isinstance(names, list):
            names = []
        if not isinstance(prefixes, list):
            prefixes = []
        rows: Dict[str, str] = {}
        for raw in names:
            key = str(raw or "").strip()
            if not key:
                continue
            val = os.getenv(key, "")
            if (val == "") and (not include_empty):
                continue
            if redact_sensitive and self._should_redact(key) and val:
                val = "***"
            rows[key] = val
        if prefixes:
            for key, val in os.environ.items():
                for raw_prefix in prefixes:
                    prefix = str(raw_prefix or "").strip()
                    if not prefix:
                        continue
                    if key.startswith(prefix):
                        out = val
                        if redact_sensitive and self._should_redact(key) and out:
                            out = "***"
                        if (out == "") and (not include_empty):
                            continue
                        rows[key] = out
                        break
        return {"count": len(rows), "env": dict(sorted(rows.items(), key=lambda kv: kv[0]))}
