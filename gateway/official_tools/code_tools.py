from __future__ import annotations

import sys
import time
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict, Optional

from agentkit.security.sandbox import get_sandbox_policy
from agentkit.security.process_sandbox import SandboxedProcessRunner
from gateway.capability_service import ToolInvocationContext

from .workspace_tools import _resolve_identity, _safe_path_under_root


class CodeRunPythonTool:
    tool_id = "code.run_python"
    name = "code.run_python"
    description = "Run a short Python script in the current workspace under sandbox policy."
    official = True
    official_domain = "code"
    side_effect_level = "privileged_host_action"

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
        script_path = run_dir / f"snippet-{uuid4().hex}.py"
        script_path.write_text(code, encoding="utf-8")

        started = time.time()
        sandbox = get_sandbox_policy()
        executable = sys.executable
        try:
            proc = await SandboxedProcessRunner(sandbox=sandbox).run_async(
                [executable, str(script_path)],
                cwd=root, workspace_root=root, timeout=timeout_s,
                session_id=ctx.session_id if ctx else None,
            )
        finally:
            script_path.unlink(missing_ok=True)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return {
            "ok": proc.returncode == 0,
            "workspace_id": handle.workspace_id,
            "returncode": proc.returncode,
            "sandbox": proc.sandbox,
            "stdout": stdout[:max_output_chars],
            "stderr": stderr[:max_output_chars],
            "truncated_stdout": len(stdout) > max_output_chars,
            "truncated_stderr": len(stderr) > max_output_chars,
            "duration_ms": int((time.time() - started) * 1000),
        }
