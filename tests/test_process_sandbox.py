import asyncio
import sys
from pathlib import Path

import pytest
import psutil

from agentkit.security.process_sandbox import (
    BubblewrapProvider,
    ConfinedCommand,
    ProcessSandboxPolicy,
    SandboxUnavailableError,
    SandboxedProcessRunner,
    SeatbeltProvider,
    WindowsRestrictedTokenProvider,
)
from agentkit.security.sandbox import SandboxPolicy


def test_linux_provider_confines_file_writes_and_network(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: "/usr/bin/bwrap")
    policy = ProcessSandboxPolicy("workspace-write", tmp_path)

    spec = BubblewrapProvider().confine(["python", "-V"], policy, cwd=tmp_path, env=None)

    assert spec.backend == "bubblewrap"
    assert spec.enforcement == "partial"
    assert "--unshare-all" in spec.argv
    assert spec.argv[-2:] == ("python", "-V")
    assert spec.argv[spec.argv.index("--bind") + 1] == str(tmp_path.resolve())
    assert spec.env["HOME"] == str(tmp_path.resolve())

    ro = BubblewrapProvider().confine(["true"], ProcessSandboxPolicy("read-only", tmp_path), cwd=tmp_path, env=None)
    assert "--bind" not in ro.argv


def test_macos_provider_uses_seatbelt_profile(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: "/usr/bin/sandbox-exec")
    spec = SeatbeltProvider().confine(["python", "-V"], ProcessSandboxPolicy("workspace-write", tmp_path), cwd=tmp_path, env=None)

    assert spec.backend == "seatbelt"
    assert "(deny file-write*)" in spec.argv[2]
    assert "(deny network*)" in spec.argv[2]
    assert str(tmp_path.resolve()).replace("\\", "\\\\") in spec.argv[2]
    assert spec.enforcement == "partial"


@pytest.mark.parametrize("provider", [BubblewrapProvider(), SeatbeltProvider()])
def test_host_credentials_are_not_inherited(monkeypatch, tmp_path, provider):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setenv("PROMETHEA_API_KEY", "secret")
    spec = provider.confine(["python", "-V"], ProcessSandboxPolicy("read-only", tmp_path), cwd=tmp_path, env=None)
    assert "PROMETHEA_API_KEY" not in spec.env
    with pytest.raises(ValueError, match="explicit environment"):
        provider.confine(["python", "-V"], ProcessSandboxPolicy("read-only", tmp_path), cwd=tmp_path, env={"PROMETHEA_API_KEY": "secret"})


def test_windows_native_runner_uses_host_argv_and_strips_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: "cmd.exe")
    monkeypatch.setenv("PROMETHEA_API_KEY", "secret")
    spec = WindowsRestrictedTokenProvider().confine(
        ["cmd", "/c", "echo", "hello"], ProcessSandboxPolicy("workspace-write", tmp_path),
        cwd=tmp_path, env=None,
    )

    assert spec.backend == "windows-restricted-token"
    assert spec.enforcement == "partial"
    assert spec.argv[:2] == (sys.executable, str(Path(__file__).resolve().parents[1] / "agentkit/security/windows_native_sandbox.py"))
    assert spec.argv[spec.argv.index("--workspace") + 1] == str(tmp_path.resolve())
    assert spec.argv[-4:] == ("cmd", "/c", "echo", "hello")
    assert "PROMETHEA_API_KEY" not in spec.env


def test_windows_native_runner_rejects_outside_cwd_and_explicit_environment(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: "cmd.exe")
    provider = WindowsRestrictedTokenProvider()
    policy = ProcessSandboxPolicy("workspace-write", tmp_path)

    with pytest.raises(PermissionError, match="outside sandbox workspace"):
        provider.confine(["cmd", "/c", "echo"], policy, cwd=tmp_path.parent, env=None)
    with pytest.raises(ValueError, match="explicit environment"):
        provider.confine(["cmd", "/c", "echo"], policy, cwd=tmp_path, env={"API_KEY": "secret"})


def test_confined_runner_rejects_missing_backend_and_outside_cwd(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: None)
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["python"]),
        provider=BubblewrapProvider(),
    )

    with pytest.raises(SandboxUnavailableError):
        runner.prepare(["python", "-V"], cwd=tmp_path, workspace_root=tmp_path)
    with pytest.raises(PermissionError, match="outside sandbox workspace"):
        runner.prepare(["python", "-V"], cwd=tmp_path.parent, workspace_root=tmp_path)


def test_only_explicitly_disabled_policy_can_return_host_command(tmp_path):
    runner = SandboxedProcessRunner(sandbox=SandboxPolicy(enabled=False))
    spec = runner.prepare(["python", "-V"], cwd=tmp_path, workspace_root=tmp_path)
    assert spec.backend == "host"
    assert spec.enforcement == "none"


def test_windows_default_provider_fails_closed_without_command_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr("agentkit.security.process_sandbox.platform.system", lambda: "Windows")
    monkeypatch.setattr("agentkit.security.process_sandbox.shutil.which", lambda name: None)
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["python"]),
    )

    with pytest.raises(SandboxUnavailableError, match="interpreter"):
        runner.prepare(["python", "-V"], cwd=tmp_path, workspace_root=tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows ACLs")
def test_native_windows_runner_restricts_real_file_writes(tmp_path):
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    if win32security.IsTokenRestricted(token):
        pytest.skip("an already-restricted test process cannot create a write-restricted token")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["cmd"]),
    )
    inside = runner.run("cmd /c echo inside>inside.txt", cwd=workspace,
                        workspace_root=workspace, shell=True, timeout=10)
    assert inside.returncode == 0, inside.stderr
    assert (workspace / "inside.txt").read_text(encoding="utf-8").strip() == "inside"

    outside = runner.run("cmd /c echo outside>..\\outside.txt", cwd=workspace,
                         workspace_root=workspace, shell=True, timeout=10)
    assert outside.returncode != 0
    assert not (tmp_path / "outside.txt").exists()

    read_only = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["cmd"], workspace_access="ro"),
    ).run("cmd /c echo forbidden>read_only.txt", cwd=workspace,
          workspace_root=workspace, shell=True, timeout=10)
    assert read_only.returncode != 0
    assert not (workspace / "read_only.txt").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows jobs")
async def test_native_windows_cancellation_terminates_child_process(tmp_path):
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    if win32security.IsTokenRestricted(token):
        pytest.skip("an already-restricted test process cannot create a write-restricted token")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["python"]),
    )
    script = "import os,time; open('child.pid','w').write(str(os.getpid())); time.sleep(30)"
    task = asyncio.create_task(runner.run_async(
        ["python", "-c", script], cwd=workspace, workspace_root=workspace, timeout=30,
    ))
    pid_file = workspace / "child.pid"
    try:
        for _ in range(100):
            if pid_file.exists():
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        assert pid_file.exists(), "sandboxed child did not start"
        child_pid = int(pid_file.read_text(encoding="utf-8"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(100):
            if not psutil.pid_exists(child_pid):
                break
            await asyncio.sleep(0.05)
        assert not psutil.pid_exists(child_pid)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_synchronous_failure_cleans_up_provider_resource(monkeypatch, tmp_path):
    class _Provider:
        def confine(self, argv, policy, *, cwd, env):
            return ConfinedCommand(
                ("sandbox", "run", "test"), cwd, None, "mock", "partial",
                ("sandbox", "cleanup", "test"),
            )

    seen = []

    def _run(argv, **kwargs):
        seen.append(tuple(argv))
        if "run" in argv:
            raise RuntimeError("runner failed")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("agentkit.security.process_sandbox.subprocess.run", _run)
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["python"]),
        provider=_Provider(),
    )

    with pytest.raises(RuntimeError, match="runner failed"):
        runner.run(["python", "-V"], cwd=tmp_path, workspace_root=tmp_path)

    assert seen[-1] == ("sandbox", "cleanup", "test")


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancel", "timeout"])
async def test_async_interruption_terminates_process_and_provider_resource(monkeypatch, tmp_path, interruption):
    started = asyncio.Event()
    cleanup = []

    class _Provider:
        def confine(self, argv, policy, *, cwd, env):
            return ConfinedCommand(
                ("sandbox", "run", "test"), cwd, None, "mock", "partial",
                ("sandbox", "cleanup", "test"),
            )

    class _Process:
        returncode = None
        killed = False

        async def communicate(self):
            if not self.killed:
                started.set()
                await asyncio.Event().wait()
            self.returncode = -9
            return b"", b""

        def kill(self):
            self.killed = True

    process = _Process()

    async def _spawn(*args, **kwargs):
        return process

    monkeypatch.setattr("agentkit.security.process_sandbox.asyncio.create_subprocess_exec", _spawn)
    monkeypatch.setattr("agentkit.security.process_sandbox.cleanup_confined_process", lambda spec: cleanup.append(spec.cleanup_argv))
    runner = SandboxedProcessRunner(
        sandbox=SandboxPolicy(command_mode="allowlist", allowed_commands=["python"]),
        provider=_Provider(),
    )
    task = asyncio.create_task(runner.run_async(
        ["python", "script.py"], cwd=tmp_path, workspace_root=tmp_path,
        timeout=0.01 if interruption == "timeout" else None,
    ))
    await started.wait()
    if interruption == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(TimeoutError):
            await task
    assert process.killed
    assert cleanup == [("sandbox", "cleanup", "test")]
