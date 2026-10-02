"""OS-backed process confinement for agent-originated commands.

The policy decides whether a command may run; a provider below supplies the
actual process boundary. A missing provider is an error, never a bare spawn.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from agentkit.security.sandbox import SandboxPolicy, get_sandbox_policy


class SandboxUnavailableError(RuntimeError):
    code = "SANDBOX_UNAVAILABLE"


@dataclass(frozen=True)
class ProcessSandboxPolicy:
    mode: str
    workspace_root: Path
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"read-only", "workspace-write"}:
            raise ValueError(f"unsupported sandbox mode: {self.mode}")
        root = self.workspace_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"sandbox workspace is not a directory: {root}")
        object.__setattr__(self, "workspace_root", root)


@dataclass(frozen=True)
class ConfinedCommand:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str] | None
    backend: str
    enforcement: str
    cleanup_argv: tuple[str, ...] | None = None

    @property
    def sandbox_metadata(self) -> dict[str, str]:
        return {"backend": self.backend, "enforcement": self.enforcement}


class SandboxedProcessResult(subprocess.CompletedProcess[str]):
    def __init__(self, result: subprocess.CompletedProcess[str], spec: ConfinedCommand) -> None:
        super().__init__(result.args, result.returncode, result.stdout, result.stderr)
        self.sandbox = spec.sandbox_metadata


class ProcessSandboxProvider(Protocol):
    def confine(
        self,
        argv: Sequence[str],
        policy: ProcessSandboxPolicy,
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
    ) -> ConfinedCommand: ...


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"process cwd outside sandbox workspace: {resolved}") from exc
    return resolved


def _validated_argv(argv: Sequence[str]) -> tuple[str, ...]:
    values = tuple(str(value) for value in argv)
    if not values or any(not value or "\x00" in value for value in values):
        raise ValueError("sandbox argv must contain non-empty arguments without NUL")
    return values


def _restricted_env(workspace: Path) -> dict[str, str]:
    """Pass only process basics, never the Runtime's credentials."""
    keys = ("PATH", "LANG", "LC_ALL", "TZ")
    if platform.system() == "Windows":
        keys = ("PATH", "PATHEXT", "SystemRoot", "WINDIR", "COMSPEC",
                "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
    result = {key: os.environ[key] for key in keys if key in os.environ}
    result["PATH"] = str(Path(sys.executable).parent) + os.pathsep + result.get("PATH", "")
    result["HOME"] = str(workspace)
    return result


class BubblewrapProvider:
    def confine(self, argv, policy, *, cwd, env):
        if env:
            raise ValueError("explicit environment is not supported by the process sandbox")
        runner = shutil.which("bwrap")
        if not runner:
            raise SandboxUnavailableError("bubblewrap is not installed")
        root = policy.workspace_root
        cwd = _inside(cwd, root)
        args = [runner, "--die-with-parent", "--new-session", "--unshare-all",
                "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev"]
        if policy.mode == "workspace-write":
            args += ["--bind", str(root), str(root)]
        args += ["--chdir", str(cwd), "--", *_validated_argv(argv)]
        return ConfinedCommand(tuple(args), cwd, _restricted_env(root), "bubblewrap", "partial")


class SeatbeltProvider:
    def confine(self, argv, policy, *, cwd, env):
        if env:
            raise ValueError("explicit environment is not supported by the process sandbox")
        runner = shutil.which("sandbox-exec")
        if not runner:
            raise SandboxUnavailableError("macOS sandbox-exec is unavailable")
        cwd = _inside(cwd, policy.workspace_root)
        # The profile permits reads, but denies file writes and network globally.
        # A private temp directory is not granted: callers must use workspace files.
        profile = ["(version 1)", "(allow default)", "(deny file-write*)",
                   "(deny network*)", '(allow file-write* (literal "/dev/null"))']
        if policy.mode == "workspace-write":
            escaped = str(policy.workspace_root).replace("\\", "\\\\").replace('"', '\\"')
            profile.append(f'(allow file-write* (subpath "{escaped}"))')
        return ConfinedCommand(
            (runner, "-p", "\n".join(profile), *_validated_argv(argv)),
            cwd, _restricted_env(policy.workspace_root), "seatbelt", "partial",
        )


class WindowsRestrictedTokenProvider:
    """Use Promethea's native Windows ACL and restricted-token runner."""

    def confine(self, argv, policy, *, cwd, env):
        if env:
            raise ValueError("explicit environment is not supported by the Windows sandbox")
        if not shutil.which("cmd"):
            raise SandboxUnavailableError("Windows command interpreter is unavailable")
        try:
            import win32security  # noqa: F401
        except ImportError as exc:
            raise SandboxUnavailableError("pywin32 is required for the Windows sandbox") from exc
        cwd = _inside(cwd, policy.workspace_root)
        runner = Path(__file__).with_name("windows_native_sandbox.py")
        return ConfinedCommand(
            (sys.executable, str(runner), "--workspace", str(policy.workspace_root),
             "--cwd", str(cwd), "--mode", policy.mode, "--", *_validated_argv(argv)),
            cwd, _restricted_env(policy.workspace_root), "windows-restricted-token", "partial",
        )


def default_provider() -> ProcessSandboxProvider:
    system = platform.system()
    if system == "Linux":
        return BubblewrapProvider()
    if system == "Darwin":
        return SeatbeltProvider()
    if system == "Windows":
        return WindowsRestrictedTokenProvider()
    raise SandboxUnavailableError(f"no process sandbox provider for {system}")


class SandboxedProcessRunner:
    def __init__(self, *, sandbox: SandboxPolicy | None = None,
                 provider: ProcessSandboxProvider | None = None) -> None:
        self.sandbox = sandbox or get_sandbox_policy()
        self.provider = provider

    def prepare(self, command: str | Sequence[str], *, cwd: str | Path = ".",
                workspace_root: str | Path | None = None, shell: bool = False,
                env: Mapping[str, str] | None = None,
                session_id: str | None = None) -> ConfinedCommand:
        raw_root = Path(workspace_root or Path.cwd()).absolute()
        root = raw_root.resolve(strict=True)
        if root != raw_root:
            raise PermissionError("sandbox workspace root must not redirect through a link")
        workdir = Path(cwd)
        if not workdir.is_absolute():
            workdir = root / workdir
        workdir = _inside(workdir, root)
        if isinstance(command, str):
            if not command.strip():
                raise ValueError("command is empty")
            argv = self._shell_argv(command, host=not self.sandbox.is_enforced()) if shell else shlex.split(command, posix=os.name != "nt")
            policy_text = command
        else:
            argv = _validated_argv(command)
            policy_text = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        decision = self.sandbox.check_command(policy_text, cwd=str(workdir), workspace_root=root)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked command: {decision.reason}")
        if not self.sandbox.is_enforced():
            return ConfinedCommand(tuple(argv), workdir, env, "host", "none")
        mode = "read-only" if self.sandbox.workspace_access == "ro" else "workspace-write"
        policy = ProcessSandboxPolicy(mode, root, session_id)
        return (self.provider or default_provider()).confine(argv, policy, cwd=workdir, env=env)

    @staticmethod
    def _shell_argv(command: str, *, host: bool = False) -> tuple[str, ...]:
        if platform.system() == "Windows":
            return (os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command)
        return ("/bin/sh", "-lc", command)

    def run(self, command: str | Sequence[str], *, cwd: str | Path = ".",
            workspace_root: str | Path | None = None, shell: bool = False,
            env: Mapping[str, str] | None = None, timeout: float | None = None,
            session_id: str | None = None) -> SandboxedProcessResult:
        spec = self.prepare(command, cwd=cwd, workspace_root=workspace_root,
                            shell=shell, env=env, session_id=session_id)
        try:
            result = subprocess.run(spec.argv, cwd=spec.cwd, env=spec.env, shell=False,
                                    capture_output=True, text=True, timeout=timeout,
                                    encoding="utf-8", errors="replace", check=False)
            _check_runner_failure(spec, result)
            return SandboxedProcessResult(result, spec)
        except BaseException:
            cleanup_confined_process(spec)
            raise

    async def run_async(self, command: str | Sequence[str], *, cwd: str | Path = ".",
                        workspace_root: str | Path | None = None, shell: bool = False,
                        env: Mapping[str, str] | None = None, timeout: float | None = None,
                        session_id: str | None = None) -> SandboxedProcessResult:
        spec = self.prepare(command, cwd=cwd, workspace_root=workspace_root,
                            shell=shell, env=env, session_id=session_id)
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv, cwd=spec.cwd, env=spec.env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            result = subprocess.CompletedProcess(
                spec.argv, process.returncode,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
            _check_runner_failure(spec, result)
            return SandboxedProcessResult(result, spec)
        except BaseException:
            if process is not None and process.returncode is None:
                process.kill()
            if spec.cleanup_argv:
                await asyncio.shield(asyncio.to_thread(cleanup_confined_process, spec))
            if process is not None:
                await asyncio.shield(process.communicate())
            raise

    def popen(self, command: str | Sequence[str], *, cwd: str | Path = ".",
              workspace_root: str | Path | None = None, shell: bool = False,
              env: Mapping[str, str] | None = None,
              session_id: str | None = None) -> _ManagedProcess:
        spec = self.prepare(command, cwd=cwd, workspace_root=workspace_root,
                            shell=shell, env=env, session_id=session_id)
        process = subprocess.Popen(spec.argv, cwd=spec.cwd, env=spec.env, shell=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
        return _ManagedProcess(process, spec)


def cleanup_confined_process(spec: ConfinedCommand) -> None:
    if not spec.cleanup_argv:
        return
    result = subprocess.run(spec.cleanup_argv, capture_output=True, text=True,
                            timeout=15, check=False)
    if result.returncode:
        raise SandboxUnavailableError(f"sandbox process cleanup failed: {result.stderr.strip()}")


def _check_runner_failure(spec: ConfinedCommand, result: subprocess.CompletedProcess[str]) -> None:
    if (spec.backend == "windows-restricted-token" and result.returncode == 127
            and "promethea-windows-sandbox:" in (result.stderr or "")):
        raise SandboxUnavailableError(result.stderr.strip())


class _ManagedProcess:
    """Keep a provider's cleanup action attached to its CLI process."""

    def __init__(self, process: subprocess.Popen[str], spec: ConfinedCommand) -> None:
        self._process = process
        self._spec = spec
        self.sandbox = spec.sandbox_metadata

    def __getattr__(self, name: str):
        return getattr(self._process, name)

    def terminate(self) -> None:
        self._process.terminate()
        cleanup_confined_process(self._spec)

    def kill(self) -> None:
        self._process.kill()
        cleanup_confined_process(self._spec)
