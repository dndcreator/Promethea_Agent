from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agentkit.security.sandbox import get_sandbox_policy
from gateway.tool_service import ToolInvocationContext

from .workspace_tools import _resolve_identity, _safe_path_under_root


class CodeRunPythonTool:
    tool_id = "code.run_python"
    name = "code.run_python"
    description = "Run a short Python script in the current workspace under sandbox policy."
    official = True
    official_domain = "code"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        code = str((args or {}).get("code") or "")
        if not code.strip():
            raise ValueError("code is required")
        timeout_s = int((args or {}).get("timeout_s") or 30)
        timeout_s = max(1, min(timeout_s, 120))
        max_output_chars = int((args or {}).get("max_output_chars") or 20000)
        max_output_chars = max(200, min(max_output_chars, 200000))

        user_id, workspace_id = _resolve_identity(args, ctx)
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        run_dir = _safe_path_under_root(root, ".runtime/code")
        run_dir.mkdir(parents=True, exist_ok=True)
        script_path = run_dir / "snippet.py"
        script_path.write_text(code, encoding="utf-8")

        command_for_policy = f"python {script_path}"
        decision = get_sandbox_policy().check_command(command_for_policy, cwd=str(root))
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked python execution: {decision.reason}")

        started = time.time()
        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(script_path)],
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return {
            "ok": proc.returncode == 0,
            "workspace_id": handle.workspace_id,
            "returncode": proc.returncode,
            "stdout": stdout[:max_output_chars],
            "stderr": stderr[:max_output_chars],
            "truncated_stdout": len(stdout) > max_output_chars,
            "truncated_stderr": len(stderr) > max_output_chars,
            "duration_ms": int((time.time() - started) * 1000),
        }
