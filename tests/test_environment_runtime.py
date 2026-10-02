from pathlib import Path

import pytest

from computer.environment import EnvironmentController
from computer.execution_context import bind_workspace
from computer.base import ComputerResult
from computer.runtime import ComputerRuntime
from computer.execution_context import ComputerWorkspace
from gateway.capability_service import CapabilityService
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.workspace_service import WorkspaceHandle


@pytest.mark.asyncio
async def test_environment_records_trusted_execution_scope(tmp_path: Path):
    app = tmp_path / "draft"
    app.mkdir()
    (app / "index.html").write_text("<h1>Draft</h1>", encoding="utf-8")
    controller = EnvironmentController(str(tmp_path))
    assert await controller.initialize()
    handle = WorkspaceHandle(workspace_id="session-1", user_id="user-1", root_path=str(tmp_path))

    with bind_workspace(handle, {"session_id": "session-1", "task_id": "task-1", "run_id": "run-1"}):
        result = await controller.execute(
            "register",
            {"name": "Draft", "root": "draft", "entrypoint": "index.html"},
        )

    assert result.success is True
    assert result.result["task_id"] == "task-1"
    assert result.result["run_id"] == "run-1"
    assert result.result["session_id"] == "session-1"
    assert "command" not in result.result
    assert (tmp_path / ".promethea" / "environments.json").is_file()


@pytest.mark.asyncio
async def test_environment_rejects_paths_outside_workspace(tmp_path: Path):
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    result = await controller.execute(
        "register",
        {"name": "Escape", "root": "..", "entrypoint": "index.html"},
    )
    assert result.success is False
    assert "escapes workspace" in str(result.error)


@pytest.mark.asyncio
async def test_process_environment_rejects_privileged_port(tmp_path: Path):
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    result = await controller.execute(
        "register",
        {"name": "App", "kind": "process", "port": 80},
    )
    assert result.success is False
    assert "port is out of range" in str(result.error)


@pytest.mark.asyncio
async def test_static_environment_remains_available_after_restart(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    registered = await controller.execute("register", {"name": "App"})
    environment_id = registered.result["environment_id"]
    launched = await controller.execute("launch", {"environment_id": environment_id})
    assert launched.result["status"] == "running"

    recovered = EnvironmentController(str(tmp_path))
    await recovered.initialize()
    current = await recovered.execute("get", {"environment_id": environment_id})
    assert current.result["status"] == "running"


@pytest.mark.asyncio
async def test_process_command_is_bound_to_confirmed_launch(tmp_path: Path):
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    rejected = await controller.execute(
        "register",
        {"name": "App", "kind": "process", "port": 8123, "command": "python server.py"},
    )
    assert rejected.success is False
    assert "only by launch" in str(rejected.error)

    registered = await controller.execute(
        "register",
        {"name": "App", "kind": "process", "port": 8123},
    )
    environment_id = registered.result["environment_id"]
    missing = await controller.execute("launch", {"environment_id": environment_id})
    assert missing.success is False
    assert "requires command" in str(missing.error)

    stale = await controller.execute(
        "launch",
        {"environment_id": environment_id, "command": "python server.py", "expected_revision": 999},
    )
    assert stale.success is False
    assert "revision changed" in str(stale.error)


@pytest.mark.asyncio
async def test_process_environment_does_not_require_a_static_entrypoint(tmp_path: Path):
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    registered = await controller.execute(
        "register",
        {"name": "Dev server", "kind": "process", "port": 8124, "entrypoint": "/"},
    )
    assert registered.success is True
    assert registered.result["kind"] == "process"
    assert registered.result["revision"] == 1


@pytest.mark.asyncio
async def test_capability_service_emits_environment_lifecycle_with_task_scope(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    emitter = EventEmitter()
    runtime = ComputerRuntime({"environment": EnvironmentController})
    service = CapabilityService(event_emitter=emitter, computer_runtime=runtime)
    handle = WorkspaceHandle(workspace_id="ws1", user_id="u1", root_path=str(tmp_path))

    with bind_workspace(handle, {"session_id": "s1", "task_id": "t1", "run_id": "r1"}):
        result = await service.execute_computer_action(
            "environment", "register", {"name": "Draft", "kind": "static"},
        )

    assert result.success is True
    event = emitter.get_history(EventType.ENVIRONMENT_STATE_CHANGED)[-1]
    assert event.payload["environment_id"] == result.result["environment_id"]
    assert event.payload["task_id"] == "t1"
    assert event.payload["status"] == "ready"
    await runtime.close()


@pytest.mark.asyncio
async def test_environment_migrates_legacy_stored_commands(tmp_path: Path):
    state_dir = tmp_path / ".promethea"
    state_dir.mkdir()
    state_path = state_dir / "environments.json"
    state_path.write_text(
        '{"version": 1, "environments": {"env1": {'
        '"environment_id": "env1", "name": "Legacy", "kind": "process", '
        '"root": ".", "entrypoint": "/", "port": 8125, "status": "stopped", '
        '"revision": 1, "command": "python old_server.py"}}}',
        encoding="utf-8",
    )

    controller = EnvironmentController(str(tmp_path))
    assert await controller.initialize()
    assert "command" not in controller.environments["env1"]
    assert controller.environments["env1"]["revision"] == 2
    assert "command" not in state_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_computer_runtime_resolves_declared_capability_aliases(tmp_path: Path):
    class Controller:
        is_initialized = False

        async def initialize(self):
            self.is_initialized = True
            return True

        async def cleanup(self):
            return True

        async def execute(self, action, params):
            return ComputerResult(success=True, result=action)

        def has_background_activity(self):
            return False

    runtime = ComputerRuntime(
        {"screen": lambda **_: Controller()},
        capability_aliases={"mouse": "screen"},
    )
    scope = ComputerWorkspace("user", "workspace", tmp_path)
    result = await runtime.execute(scope, "mouse", "click", {})
    assert result.success is True
    assert result.result == "click"
