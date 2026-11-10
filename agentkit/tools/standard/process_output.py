"""Shared structured receipts for workspace process tools."""

from agentkit.security.process_sandbox import SandboxedProcessResult


def process_output(proc: SandboxedProcessResult, *, max_chars: int) -> dict:
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    result = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "sandbox": proc.sandbox,
        "stdout": stdout[:max_chars],
        "stderr": stderr[:max_chars],
        "truncated_stdout": len(stdout) > max_chars,
        "truncated_stderr": len(stderr) > max_chars,
    }
    if proc.returncode != 0:
        diagnostic = stderr.rstrip()
        diagnostic_limit = min(512, max_chars)
        result["error_detail"] = {
            "code": "PROCESS_EXIT_NONZERO",
            "category": "process",
            "message": f"Process exited with code {proc.returncode}.",
            "retryable": False,
            "details": {
                "returncode": proc.returncode,
                "stderr_tail": diagnostic[-diagnostic_limit:],
                "stderr_tail_truncated": len(diagnostic) > diagnostic_limit,
            },
        }
    return result
