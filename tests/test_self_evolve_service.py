import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentkit.mcp.invocation_context import bind_invocation_context
from agentkit.security.approval import approval_scope
from agentkit.security.sandbox import SandboxPolicy
from agentkit.tools.self_evolve.self_evolve import SelfEvolveService
from gateway.capability_service import CapabilityService, ToolInvocationContext
from gateway.self_model_service import SelfModelService


@pytest.fixture(autouse=True)
def _authenticated_user():
    with bind_invocation_context({"user_id": "u1"}):
        yield


def _make_workspace() -> Path:
    base = Path(os.environ.get("PROMETHEA_TEST_TMP_ROOT", ".tmp/pytest-runtime")) / "self-evolve-work"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    (base / "extensions" / "community").mkdir(parents=True, exist_ok=True)
    return base.resolve()


def _make_service(workspace: Path) -> SelfEvolveService:
    service = SelfEvolveService(
        workspace_root=str(workspace),
        self_model_service=SelfModelService(workspace_root=str(workspace)),
    )
    capability_service = CapabilityService()
    service.configure_extension_reloader(capability_service.reload_discovered_tools)
    service._test_capability_service = capability_service
    return service


async def _create_echo_task(service: SelfEvolveService, *, version: str = "1.0.0") -> dict:
    return await service.evolve_create_task(
        goal="Add an isolated echo capability",
        capability_id="echo_tool",
        version=version,
        description="Echo structured text",
        commands=[
            {
                "command": "echo",
                "description": "Return the supplied text",
                "test_args": {"text": "hello"},
            }
        ],
    )


@pytest.mark.asyncio
async def test_self_evolve_writes_only_inside_capability_staging():
    ws = _make_workspace()
    try:
        service = _make_service(ws)
        created = await _create_echo_task(service)
        task_id = created["task"]["task_id"]

        result = await service.evolve_write_file(
            task_id,
            "tool.py",
            "async def handle(command, args):\n    return {'text': args.get('text', '')}\n",
        )
        assert result["ok"] is True
        assert (service._task_root(task_id) / "tool.py").is_file()

        with pytest.raises((ValueError, PermissionError)):
            await service.evolve_write_file(task_id, "../../gateway/server.py", "broken")
        with pytest.raises(PermissionError):
            await service.evolve_write_file(task_id, "agent-manifest.json", "{}")
        assert not (ws / "gateway" / "server.py").exists()
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_validates_publishes_and_invokes_generated_tool(monkeypatch):
    ws = _make_workspace()
    service_name = ""
    try:
        monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
        service = _make_service(ws)
        created = await _create_echo_task(service)
        service_name = service._service_name(created["task"])
        task_id = created["task"]["task_id"]
        await service.evolve_write_file(
            task_id,
            "tool.py",
            "async def handle(command, args):\n"
            "    if command != 'echo':\n"
            "        raise ValueError(command)\n"
            "    return {'text': args.get('text', '')}\n",
        )

        validated = await service.evolve_validate(task_id)
        assert validated["ok"] is True
        assert validated["smoke_tests"] == [{"command": "echo", "ok": True, "result": {"text": "hello"}}]

        published = await service.evolve_publish(task_id)
        assert published["ok"] is True
        assert published["service_name"] == service_name
        assert published["tool_ids"] == [f"{service_name}.echo"]
        capability_service = service._test_capability_service
        assert f"{service_name}.echo" in capability_service._registered_tools
        params = {"text": "approved"}
        with approval_scope(f"{service_name}.echo", params, confirmed=True):
            result = await capability_service.call_tool(
                f"{service_name}.echo",
                params,
                ctx=ToolInvocationContext(user_id="u1"),
            )
        assert result == {"text": "approved"}

        with pytest.raises(PermissionError):
            await service.evolve_write_file(task_id, "tool.py", "changed")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_rejects_unvalidated_and_conflicting_versions(monkeypatch):
    ws = _make_workspace()
    service_name = ""
    try:
        monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
        service = _make_service(ws)
        first = await _create_echo_task(service)
        service_name = service._service_name(first["task"])
        first_id = first["task"]["task_id"]
        with pytest.raises(ValueError):
            await service.evolve_publish(first_id)

        implementation = "async def handle(command, args):\n    return args\n"
        await service.evolve_write_file(first_id, "tool.py", implementation)
        assert (await service.evolve_validate(first_id))["ok"] is True
        await service.evolve_publish(first_id)

        second = await _create_echo_task(service)
        second_id = second["task"]["task_id"]
        await service.evolve_write_file(second_id, "tool.py", implementation + "# different\n")
        assert (await service.evolve_validate(second_id))["ok"] is True
        with pytest.raises(FileExistsError):
            await service.evolve_publish(second_id)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_rejects_changes_after_validation(monkeypatch):
    ws = _make_workspace()
    try:
        monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
        service = _make_service(ws)
        created = await _create_echo_task(service)
        task_id = created["task"]["task_id"]
        entry = service._task_root(task_id) / "tool.py"
        entry.write_text("async def handle(command, args):\n    return args\n", encoding="utf-8")
        assert (await service.evolve_validate(task_id))["ok"] is True

        entry.write_text("async def handle(command, args):\n    return {'changed': True}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="changed after validation"):
            await service.evolve_publish(task_id)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_rejects_changes_during_validation(monkeypatch):
    ws = _make_workspace()
    try:
        service = _make_service(ws)
        created = await _create_echo_task(service)
        task_id = created["task"]["task_id"]
        entry = service._task_root(task_id) / "tool.py"
        entry.write_text("async def handle(command, args):\n    return args\n", encoding="utf-8")

        async def _mutating_invoke(_self, _command, _args, *, require_approval=True):
            _ = require_approval
            entry.write_text("async def handle(command, args):\n    return {'changed': True}\n", encoding="utf-8")
            return {}

        monkeypatch.setattr(
            "agentkit.tools.self_evolve.self_evolve.GeneratedCapabilityService.invoke",
            _mutating_invoke,
        )
        result = await service.evolve_validate(task_id)
        assert result["ok"] is False
        assert "changed while validation" in result["errors"][0]
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_tasks_are_private_to_their_owner():
    ws = _make_workspace()
    try:
        service = _make_service(ws)
        created = await _create_echo_task(service)
        task_id = created["task"]["task_id"]

        with bind_invocation_context({"user_id": "u2"}):
            assert (await service.evolve_list_tasks())["tasks"] == []
            with pytest.raises(FileNotFoundError):
                await service.evolve_get_task(task_id)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_requires_smoke_test_arguments():
    ws = _make_workspace()
    try:
        service = _make_service(ws)
        with pytest.raises(ValueError, match="test_args"):
            await service.evolve_create_task(
                goal="Create a tool",
                capability_id="missing_test",
                version="1.0.0",
                description="Missing smoke test",
                commands=[{"command": "run", "description": "Run"}],
            )
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_self_evolve_task_store_updates_are_atomic_across_instances():
    ws = _make_workspace()
    try:
        services = [_make_service(ws) for _ in range(2)]

        def _create(index: int) -> str:
            with bind_invocation_context({"user_id": "u1"}):
                result = asyncio.run(
                    services[index % 2].evolve_create_task(
                        goal=f"Create tool {index}",
                        capability_id=f"tool_{index}",
                        version="1.0.0",
                        description="Concurrency test",
                        commands=[{"command": "run", "description": "Run", "test_args": {}}],
                    )
                )
                return result["task"]["task_id"]

        with ThreadPoolExecutor(max_workers=4) as executor:
            task_ids = list(executor.map(_create, range(8)))

        assert len(set(task_ids)) == 8
        with bind_invocation_context({"user_id": "u1"}):
            rows = asyncio.run(services[0].evolve_list_tasks(limit=20))["tasks"]
        assert {row["task_id"] for row in rows} == set(task_ids)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_publish_is_atomic(monkeypatch):
    ws = _make_workspace()
    try:
        monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
        service = _make_service(ws)
        created = await _create_echo_task(service)
        task_id = created["task"]["task_id"]
        await service.evolve_write_file(
            task_id,
            "tool.py",
            "async def handle(command, args):\n    return args\n",
        )
        assert (await service.evolve_validate(task_id))["ok"] is True
        destination = service.publish_root / service._service_name(created["task"])

        monkeypatch.setattr("agentkit.tools.self_evolve.self_evolve.shutil.copy2", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")))
        with pytest.raises(OSError, match="copy failed"):
            await service.evolve_publish(task_id)
        assert not destination.exists()
        assert not list(service.publish_root.glob(".*.tmp"))
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_generated_capability_cannot_read_outside_its_package(monkeypatch):
    ws = _make_workspace()
    try:
        monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
        secret = ws / "private.txt"
        secret.write_text("private", encoding="utf-8")
        service = _make_service(ws)
        created = await service.evolve_create_task(
            goal="Try an out-of-scope read",
            capability_id="unsafe_reader",
            version="1.0.0",
            description="Boundary test",
            commands=[{"command": "read", "description": "Read", "test_args": {}}],
        )
        task_id = created["task"]["task_id"]
        source = (
            "async def handle(command, args):\n"
            f"    return open({str(secret)!r}, encoding='utf-8').read()\n"
        )
        await service.evolve_write_file(task_id, "tool.py", source)
        result = await service.evolve_validate(task_id)
        assert result["ok"] is False
        assert "file access denied" in result["errors"][0]
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_self_model_remains_available():
    ws = _make_workspace()
    try:
        docs = ws / "docs" / "architecture"
        docs.mkdir(parents=True, exist_ok=True)
        (ws / "docs" / "runtime-overview.md").write_text("# Runtime\n", encoding="utf-8")
        (docs / "runtime-io.md").write_text("# Runtime I/O\n", encoding="utf-8")
        (docs / "tool-runtime.md").write_text("# Tool Runtime\n", encoding="utf-8")
        (docs / "memory-model.md").write_text("# Memory Model\n", encoding="utf-8")
        (docs / "conversation-pipeline.md").write_text("# Pipeline\n", encoding="utf-8")
        (ws / "docs" / "ui-overview.md").write_text("# UI\n", encoding="utf-8")
        service = _make_service(ws)
        built = await service.evolve_build_self_model(max_chars_per_file=1000)
        assert built["ok"] is True
        current = await service.evolve_get_self_model()
        assert current["exists"] is True
    finally:
        shutil.rmtree(ws, ignore_errors=True)
