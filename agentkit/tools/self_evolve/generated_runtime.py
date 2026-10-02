"""Trusted proxy for capabilities written by the Agent.

Generated modules are never imported into the Gateway process. Each call is
executed by ``generated_runner`` inside the configured process sandbox.
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

from agentkit.mcp.invocation_context import get_invocation_context
from agentkit.security.approval import call_is_approved
from agentkit.security.process_sandbox import SandboxedProcessRunner
from agentkit.security.sandbox import SandboxPolicy, get_sandbox_policy

from .generated_runner import RESULT_PREFIX


_MAX_RUNNER_OUTPUT_BYTES = 1_100_000


class GeneratedCapabilityService:
    def __init__(
        self,
        *,
        manifest: Dict[str, Any],
        manifest_path: Path,
        runtime_root: Path | None = None,
    ):
        self.manifest = dict(manifest or {})
        self.manifest_path = Path(manifest_path).resolve()
        self.package_root = self.manifest_path.parent
        generated = self.manifest.get("generatedCapability") or {}
        self.owner_user_id = str(generated.get("ownerUserId") or "").strip()
        self.entry_script = self.package_root / str(generated.get("entryScript") or "tool.py")
        self.timeout_seconds = max(1, min(int(generated.get("timeoutSeconds") or 30), 300))
        self.name = str(self.manifest.get("name") or self.package_root.name)
        self._runtime_root = (
            Path(runtime_root).resolve()
            if runtime_root is not None
            else self._find_project_root() / ".runtime" / "generated-capabilities" / self.name
        )

    def _find_project_root(self) -> Path:
        for parent in self.package_root.parents:
            if parent.name == "extensions":
                return parent.parent
        for parent in (self.package_root, *self.package_root.parents):
            if (parent / "pyproject.toml").is_file():
                return parent
        return Path.cwd().resolve()

    @staticmethod
    def _execution_policy() -> SandboxPolicy:
        base = get_sandbox_policy()
        return SandboxPolicy(
            enabled=base.enabled,
            profile=base.profile,
            workspace_access="rw",
            command_mode="allowlist",
            allowed_commands={"python", "python.exe", Path(sys.executable).name},
            deny_fragments=base.deny_fragments,
            network_mode=base.network_mode,
            allowed_domains=base.allowed_domains,
            block_private_network=base.block_private_network,
            desktop_mode="observe_only",
            process_mode="managed_only",
        )

    async def invoke(self, command: str, args: Dict[str, Any], *, require_approval: bool = True) -> Any:
        requester_user_id = str(get_invocation_context().get("user_id") or "").strip()
        if self.owner_user_id and requester_user_id != self.owner_user_id:
            raise PermissionError("generated capability is private to another user")
        if require_approval and not call_is_approved():
            raise PermissionError("generated capability execution requires confirmation")
        if not self.entry_script.is_file():
            raise FileNotFoundError(f"generated capability entry script missing: {self.entry_script}")

        call_root = self._runtime_root / "calls" / uuid.uuid4().hex
        call_root.mkdir(parents=True, exist_ok=False)
        request_path = call_root / "request.json"
        request_path.write_text(
            json.dumps({"command": str(command), "args": dict(args or {})}, ensure_ascii=False),
            encoding="utf-8",
        )
        runner_path = Path(__file__).with_name("generated_runner.py").resolve()
        try:
            result = await SandboxedProcessRunner(sandbox=self._execution_policy()).run_async(
                [sys.executable, str(runner_path), str(self.entry_script), str(request_path)],
                cwd=call_root,
                workspace_root=call_root,
                timeout=self.timeout_seconds,
            )
            if len(str(result.stdout or "").encode("utf-8")) > _MAX_RUNNER_OUTPUT_BYTES:
                raise RuntimeError("generated capability output exceeded the size limit")
            payload = self._parse_result(result.stdout)
            if not payload.get("ok"):
                raise RuntimeError(str(payload.get("error") or "generated capability failed"))
            return payload.get("result")
        finally:
            shutil.rmtree(call_root, ignore_errors=True)

    @staticmethod
    def _parse_result(stdout: str) -> Dict[str, Any]:
        for line in reversed(str(stdout or "").splitlines()):
            if line.startswith(RESULT_PREFIX):
                payload = json.loads(line[len(RESULT_PREFIX):])
                if isinstance(payload, dict):
                    return payload
        raise RuntimeError("generated capability returned no structured result")

    def __getattr__(self, command: str):
        if command.startswith("_") or command == "handle_handoff":
            raise AttributeError(command)

        async def _call(**kwargs: Any) -> Any:
            return await self.invoke(command, kwargs, require_approval=True)

        return _call
