import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentkit.security.sandbox import SandboxPolicy
from computer.base import ComputerResult
from computer.execution_context import ComputerWorkspace, bind_workspace, current_workspace
from computer.filesystem import FileSystemController
from computer.process import ProcessController
from computer.runtime import ComputerRuntime
from gateway.capability_service import ToolInvocationContext, CapabilityService
from gateway.workspace_service import WorkspaceService


def scope(tmp_path, user, workspace="task"):
    root = tmp_path / user / workspace
    root.mkdir(parents=True, exist_ok=True)
    return ComputerWorkspace(user, workspace, root.resolve())


@pytest.mark.asyncio
async def test_filesystem_workspaces_do_not_share_files(tmp_path):
    runtime = ComputerRuntime({"filesystem": FileSystemController})
    alice, bob = scope(tmp_path, "alice"), scope(tmp_path, "bob")
    written = await runtime.execute(alice, "filesystem", "write", {"path": "result.txt", "content": "private"})
    assert written.success
    assert (alice.root / "result.txt").read_text() == "private"
    hidden = await runtime.execute(bob, "filesystem", "read", {"path": str(alice.root / "result.txt")})
    assert not hidden.success
    assert not (bob.root / "result.txt").exists()
    assert written.metadata["execution"]["desktop_isolated"] is False
    await runtime.close()


@pytest.mark.asyncio
async def test_mcp_scope_is_trusted_and_restored_after_parallel_calls(tmp_path):
    workspaces = WorkspaceService(base_dir=str(tmp_path))
    gate = asyncio.Event()
    seen = []

    async def invoke(**kwargs):
        before = current_workspace()
        seen.append(before)
        if len(seen) == 2:
            gate.set()
        await gate.wait()
        assert current_workspace() == before
        return {"ok": True, "user_id": before.user_id}

    manager = SimpleNamespace(call_service_tool=invoke, get_available_services_filtered=lambda: {})
    service = CapabilityService(mcp_manager=manager)
    service.workspace_service = workspaces
    results = await asyncio.gather(*[
        service.call_tool("fs_action", {"service_name": "computer_control", "tool_name": "fs_action"},
                          ctx=ToolInvocationContext(user_id=user, session_id="task"))
        for user in ("alice", "bob")
    ])
    assert {row["user_id"] for row in results} == {"alice", "bob"}
    assert seen[0].root != seen[1].root
    assert current_workspace() is None
    with pytest.raises(PermissionError, match="user_id differs"):
        await service.call_tool("fs_action", {"service_name": "computer_control", "user_id": "bob"},
                                ctx=ToolInvocationContext(user_id="alice", session_id="task"))
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_cancelled_tool_does_not_leak_workspace(tmp_path):
    entered = asyncio.Event()

    async def invoke(**kwargs):
        assert current_workspace().user_id == "alice"
        entered.set()
        await asyncio.Event().wait()

    service = CapabilityService(mcp_manager=SimpleNamespace(call_service_tool=invoke, get_available_services_filtered=lambda: {}))
    service.workspace_service = WorkspaceService(base_dir=str(tmp_path))
    task = asyncio.create_task(service.call_tool("fs_action", {"service_name": "computer_control"},
                              ctx=ToolInvocationContext(user_id="alice", session_id="task")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert current_workspace() is None


class FakeController:
    instances = []

    def __init__(self, workspace_root):
        self.workspace_root = workspace_root
        self.is_initialized = False
        self.closed = False
        self.active_processes = {}
        self.instances.append(self)

    async def initialize(self):
        self.is_initialized = True
        return True

    def has_background_activity(self):
        return any(process.poll() is None for process in self.active_processes.values())

    async def execute(self, action, params):
        if action == "background":
            self.active_processes[1] = SimpleNamespace(poll=lambda: None)
        return ComputerResult(success=True)

    async def cleanup(self):
        self.closed = True
        self.is_initialized = False
        return True


@pytest.mark.asyncio
async def test_idle_eviction_keeps_active_processes(tmp_path):
    runtime = ComputerRuntime({"process": FakeController}, max_workspaces=1)
    alice, bob = scope(tmp_path, "alice"), scope(tmp_path, "bob")
    assert (await runtime.execute(alice, "process", "background", {})).success
    first = FakeController.instances[-1]
    blocked = await runtime.execute(bob, "process", "read", {})
    assert not blocked.success
    assert not first.closed
    first.active_processes.clear()
    assert (await runtime.execute(bob, "process", "read", {})).success
    assert first.closed
    await runtime.close()
    assert not (await runtime.execute(alice, "process", "read", {})).success


@pytest.mark.asyncio
async def test_process_command_uses_workspace_and_preserves_failure(monkeypatch, tmp_path):
    from agentkit.security.process_sandbox import ConfinedCommand, SandboxedProcessResult
    import subprocess

    spec = ConfinedCommand(("python",), tmp_path, None, "test", "partial")
    result = SandboxedProcessResult(subprocess.CompletedProcess(["python"], 2, "", "failed"), spec)
    run = AsyncMock(return_value=result)
    monkeypatch.setattr("computer.process.SandboxedProcessRunner.run_async", run)
    controller = ProcessController(workspace_root=str(tmp_path))
    controller.is_initialized = True
    controller.sandbox = SandboxPolicy(command_mode="allowlist", allowed_commands=["python"])
    output = await controller.execute("run", {"command": "python job.py"})
    assert not output.success
    assert run.call_args.kwargs["workspace_root"] == tmp_path
    assert output.metadata["sandbox"] == {"backend": "test", "enforcement": "partial"}


@pytest.mark.asyncio
async def test_process_cancel_propagates_to_runner(monkeypatch, tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def run(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr("computer.process.SandboxedProcessRunner.run_async", run)
    controller = ProcessController(workspace_root=str(tmp_path))
    controller.is_initialized = True
    controller.sandbox = SandboxPolicy(command_mode="allowlist", allowed_commands=["python"])
    task = asyncio.create_task(controller.execute("run", {"command": "python job.py"}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_gateway_uses_bound_workspace_instead_of_project(tmp_path):
    from gateway_integration import GatewayIntegration

    gateway = GatewayIntegration(str(tmp_path / "missing.json"))
    service = CapabilityService(computer_runtime=gateway.computer_runtime)
    handle = WorkspaceService(base_dir=str(tmp_path / "workspaces")).resolve_workspace_handle(user_id="alice", workspace_id="task")
    with bind_workspace(handle):
        result = await service.execute_computer_action("filesystem", "write", {"path": "output.txt", "content": "ok"})
    assert result.success
    assert (Path(handle.root_path) / "output.txt").read_text() == "ok"
    await gateway.computer_runtime.close()


@pytest.mark.asyncio
async def test_browser_initialization_uses_scoped_state_and_chromium_sandbox(monkeypatch, tmp_path):
    from computer.browser import BrowserController

    executable = tmp_path / "browser.exe"
    executable.touch()
    browser = SimpleNamespace(new_context=AsyncMock(), close=AsyncMock())
    context = SimpleNamespace(new_page=AsyncMock(return_value=SimpleNamespace(on=Mock())),
                              storage_state=AsyncMock(), close=AsyncMock(), on=Mock())
    browser.new_context.return_value = context
    chromium = SimpleNamespace(executable_path=str(executable), launch=AsyncMock(return_value=browser))
    playwright = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=playwright)))
    controller = BrowserController(workspace_root=str(tmp_path))
    assert await controller.initialize()
    assert chromium.launch.call_args.kwargs["chromium_sandbox"] is True
    controller.page.screenshot = AsyncMock(return_value=b"png")
    blocked = await controller.execute("screenshot", {"path": str(tmp_path.parent / "outside.png")})
    assert not blocked.success
    controller.page.screenshot.assert_not_awaited()
    await controller.cleanup()
    context.storage_state.assert_awaited_once_with(path=str(tmp_path / "browser_state.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["mouse", "keyboard", "screenshot", "clipboard"])
async def test_gateway_routes_screen_capabilities_to_screen_controller(monkeypatch, tmp_path, capability):
    from gateway_integration import GatewayIntegration

    gateway = GatewayIntegration(str(tmp_path / "missing.json"))
    service = CapabilityService(computer_runtime=gateway.computer_runtime)
    resolved = []

    async def execute(scope, requested_capability, action, params):
        resolved.append(gateway.computer_runtime.capability_aliases.get(requested_capability, requested_capability))
        return ComputerResult(success=True)

    monkeypatch.setattr(gateway.computer_runtime, "execute", execute)
    handle = WorkspaceService(base_dir=str(tmp_path)).resolve_workspace_handle(user_id="alice")
    with bind_workspace(handle):
        result = await service.execute_computer_action(capability, "test", {})
    assert result.success
    assert resolved == ["screen"]


@pytest.mark.asyncio
async def test_browser_keypress_never_uses_host_keyboard(monkeypatch):
    from agentkit.tools.computer.computer_control import ComputerControlService

    service = ComputerControlService()
    execute = AsyncMock(return_value="SUCCESS")
    monkeypatch.setattr(service, "execute_action", execute)
    await service.browser_action(action="act", selector="input", key="Enter")
    execute.assert_awaited_once_with("browser", "press", {"selector": "input", "key": "Enter"})


def test_browser_snapshot_references_are_workspace_owned(tmp_path):
    from agentkit.tools.computer.computer_control import ComputerControlService

    service = ComputerControlService()
    workspaces = WorkspaceService(base_dir=str(tmp_path))
    alice = workspaces.resolve_workspace_handle(user_id="alice")
    bob = workspaces.resolve_workspace_handle(user_id="bob")
    with bind_workspace(alice):
        service._browser_snapshot_refs["n1"] = "#alice-button"
    with bind_workspace(bob):
        assert "n1" not in service._browser_snapshot_refs
        service._browser_snapshot_refs["n1"] = "#bob-button"
    with bind_workspace(alice):
        assert service._browser_snapshot_refs["n1"] == "#alice-button"


@pytest.mark.asyncio
async def test_busy_workspace_is_not_evicted(tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()

    class Busy(FakeController):
        async def execute(self, action, params):
            entered.set()
            await finish.wait()
            return ComputerResult(success=True)

    runtime = ComputerRuntime({"filesystem": Busy}, max_workspaces=1)
    task = asyncio.create_task(runtime.execute(scope(tmp_path, "alice"), "filesystem", "read", {}))
    await entered.wait()
    try:
        result = await runtime.execute(scope(tmp_path, "bob"), "filesystem", "read", {})
        assert not result.success
    finally:
        finish.set()
        await task
        await runtime.close()


@pytest.mark.asyncio
async def test_runtime_close_cancels_inflight_actions(tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class Busy(FakeController):
        async def execute(self, action, params):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    runtime = ComputerRuntime({"process": Busy})
    task = asyncio.create_task(runtime.execute(scope(tmp_path, "alice"), "process", "run", {}))
    await entered.wait()
    await asyncio.wait_for(runtime.close(), timeout=2)
    assert cancelled.is_set()
    assert task.cancelled()
    assert FakeController.instances[-1].closed


def test_workspace_service_rejects_redirected_workspace_root(tmp_path):
    from gateway.workspace_service import WorkspaceSandboxError

    service = WorkspaceService(base_dir=str(tmp_path / "workspaces"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (service.base_dir / "alice").mkdir()
    try:
        (service.base_dir / "alice" / "task").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating directory symlinks is unavailable")
    with pytest.raises(WorkspaceSandboxError, match="redirect"):
        service.resolve_workspace_handle(user_id="alice", workspace_id="task")


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows sandbox")
async def test_native_computer_process_and_files_share_confined_workspace(monkeypatch, tmp_path):
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        if win32security.IsTokenRestricted(token):
            pytest.skip("requires a non-restricted parent test process")
    finally:
        token.Close()
    monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY",
                        SandboxPolicy(command_mode="allowlist", allowed_commands=["cmd"]))
    runtime = ComputerRuntime({"process": ProcessController, "filesystem": FileSystemController})
    workspace = scope(tmp_path, "alice")
    try:
        result = await runtime.execute(workspace, "process", "run", {"command": "cmd /c echo scoped>result.txt"})
        assert result.success, result.error or result.result
        assert result.metadata["sandbox"]["backend"] == "windows-restricted-token"
        output = await runtime.execute(workspace, "filesystem", "read", {"path": "result.txt"})
        assert output.success
        assert output.result.strip() == "scoped"
        denied = await runtime.execute(workspace, "process", "run", {"command": "cmd /c echo escape>..\\outside.txt"})
        assert not denied.success
        assert not (workspace.root.parent / "outside.txt").exists()
    finally:
        await runtime.close()
