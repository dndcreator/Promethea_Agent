from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkit.mcp.invocation_context import bind_invocation_context
from agentkit.tools.self_evolve.self_evolve import SelfEvolveService
from computer.environment import EnvironmentController
from computer.execution_context import bind_workspace
from computer.runtime import ComputerRuntime
from computer.canvas_document import export_canvas_library, decode_canvas_library
from gateway.capability_service import CapabilityService
from gateway.http.routes import canvas
from gateway.http.routes.auth import get_current_user_id
from gateway.workspace_service import WorkspaceService


SPEC = {"entrypoint": "index.html", "tests": [
    {"action": "click", "selector": "#add"},
    {"action": "expect_text", "selector": "output", "value": "1"},
]}
APP = '<!doctype html><html><head><title>Counter</title></head><body><button id="add">Add</button><output>0</output><script>document.querySelector("button").onclick=()=>document.querySelector("output").textContent="1";</script></body></html>'


@pytest.fixture
def service(tmp_path):
    with bind_invocation_context({"user_id": "alice"}):
        yield SelfEvolveService(str(tmp_path))


async def create(service):
    task = (await service.evolve_create_task(goal="counter", capability_id="counter", version="1.0.0", description="Counter", canvas=SPEC))["task"]
    await service.evolve_write_file(task["task_id"], "index.html", APP)
    return task["task_id"]


@pytest.mark.asyncio
async def test_checkpoints_exact_edits_review_restore_and_revalidation(service):
    task_id = await create(service)
    context = await service.evolve_collect_context(task_id)
    sha = context["files"][0]["sha256"]
    await service.evolve_patch_file(task_id, "index.html", "Counter</title>", "Updated</title>", sha)
    review = await service.evolve_review(task_id)
    assert "+" in review["diff"] and "Updated" in review["diff"]
    with pytest.raises(ValueError, match="changed since inspection"):
        await service.evolve_write_file(task_id, "index.html", "stale", expected_sha256=sha)
    await service.evolve_restore(task_id, review["checkpoint_id"])
    assert (service._task_root(task_id) / "index.html").read_text(encoding="utf-8") == APP
    assert service._get_task_or_raise(task_id)["status"] == "draft"
    with pytest.raises((ValueError, PermissionError)):
        await service.evolve_write_file(task_id, "../gateway/server.py", "bad")
    inspected = await service.evolve_read_file(task_id, "index.html")
    assert inspected["content"].startswith("1:")
    assert (await service.evolve_search(task_id, "Counter"))["matches"]
    await service.evolve_delete_file(task_id, "index.html", inspected["sha256"])
    checkpoint = (await service.evolve_review(task_id))["checkpoint_id"]
    await service.evolve_restore(task_id, checkpoint)
    assert (service._task_root(task_id) / "index.html").read_text(encoding="utf-8") == APP


@pytest.mark.asyncio
async def test_browser_verification_failure_is_durable_and_blocks_open(service, monkeypatch):
    task_id = await create(service)
    monkeypatch.setattr("agentkit.tools.self_evolve.self_evolve.verify_canvas", AsyncMock(return_value={"ok": False, "errors": ["button not found"], "steps": []}))
    assert not (await service.evolve_validate(task_id))["ok"]
    assert service._get_task_or_raise(task_id)["validations"][-1]["errors"] == ["button not found"]
    with pytest.raises(ValueError, match="pass browser verification"):
        await service.evolve_open_canvas(task_id)


@pytest.mark.asyncio
async def test_canvas_deploy_uses_runtime_and_optional_user_library(service, tmp_path, monkeypatch):
    task_id = await create(service)
    monkeypatch.setattr("agentkit.tools.self_evolve.self_evolve.verify_canvas", AsyncMock(return_value={"ok": True, "errors": [], "steps": []}))
    assert (await service.evolve_validate(task_id))["ok"]
    runtime = ComputerRuntime({"environment": EnvironmentController})
    workspaces = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    capability = CapabilityService(computer_runtime=runtime, workspace_service=workspaces)
    service.configure_canvas_runtime(capability)
    scope = workspaces.resolve_workspace_handle(user_id="alice", workspace_id="s1")
    with bind_workspace(scope):
        first = await service.evolve_open_canvas(task_id)
        retained = await service.evolve_open_canvas(task_id, reusable=True)
    assert first["workspace_id"] == "s1" and first["lifetime"] == "session"
    assert retained["workspace_id"] == "_canvas_library" and retained["lifetime"] == "reusable"
    assert not (tmp_path / "gateway" / "server.py").exists()
    published = await service.evolve_publish(task_id)
    assert published["tool_ids"] == []
    assert not list(service.publish_root.glob("*/agent-manifest.json"))
    await runtime.close()


@pytest.mark.asyncio
async def test_state_persistence_cas_and_render_identity_are_separate(tmp_path):
    (tmp_path / "index.html").write_text(APP, encoding="utf-8")
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    row = (await controller.execute("register", {"name": "App"})).result
    params = {"environment_id": row["environment_id"], "expected_revision": 0, "value": {"count": 5}}
    assert (await controller.execute("state_set", params)).success
    assert not (await controller.execute("state_set", params)).success
    public = (await controller.execute("get", params)).result
    assert public["updated_at"] == row["updated_at"]
    assert "app_state" not in public
    restarted = EnvironmentController(str(tmp_path))
    await restarted.initialize()
    assert (await restarted.execute("state_get", params)).result == {"revision": 1, "value": {"count": 5}}


@pytest.mark.asyncio
async def test_canvas_api_state_retain_delete_and_owner_isolation(tmp_path, monkeypatch):
    workspaces = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    runtime = ComputerRuntime({"environment": EnvironmentController})
    capability = CapabilityService(computer_runtime=runtime, workspace_service=workspaces)
    monkeypatch.setattr(canvas, "get_gateway_server", lambda: SimpleNamespace(workspace_service=workspaces, capability_service=capability))
    handle = workspaces.resolve_workspace_handle(user_id="alice", workspace_id="s1")
    root = workspaces.base_dir / "alice" / "s1"
    (root / "index.html").write_text(APP, encoding="utf-8")
    with bind_workspace(handle):
        row = (await capability.execute_computer_action("environment", "register", {"name": "Counter"})).result
    app = FastAPI()
    app.include_router(canvas.router)
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    with TestClient(app) as client:
        path = f'/canvas/s1/{row["environment_id"]}'
        assert client.put(path + "/state", json={"expected_revision": 0, "value": {"count": 3}}).status_code == 200
        assert client.put(path + "/state", json={"expected_revision": 0, "value": {}}).status_code == 409
        retained = client.post(path + "/retain")
        assert retained.status_code == 200, retained.text
        saved = retained.json()
        library_path = f'/canvas/_canvas_library/{saved["environment_id"]}'
        assert client.get(library_path + "/state").json()["value"] == {"count": 3}
        bundle = export_canvas_library(workspaces.base_dir / "alice" / "_canvas_library")
        app.dependency_overrides[get_current_user_id] = lambda: "bob"
        assert client.get(library_path + "/preview/").status_code == 404
        app.dependency_overrides[get_current_user_id] = lambda: "alice"
        assert client.delete(library_path).status_code == 200
        assert not (workspaces.base_dir / "alice" / "_canvas_library" / saved["root"]).exists()
    assert await canvas.restore_canvas_library("bob", bundle) == 1
    assert await canvas.restore_canvas_library("bob", bundle) == 1
    restored = export_canvas_library(workspaces.base_dir / "bob" / "_canvas_library")
    assert restored[0]["state"]["value"] == {"count": 3}
    bundle[0]["files"]["index.html"]["sha256"] = "tampered"
    with pytest.raises(ValueError, match="checksum"):
        decode_canvas_library(bundle)
    await runtime.close()


@pytest.mark.asyncio
async def test_expected_result_is_checked_not_just_no_exception(service, monkeypatch):
    task = (await service.evolve_create_task(goal="Echo", capability_id="echo", version="1.0", description="Echo",
        commands=[{"command": "echo", "description": "Echo", "test_args": {}, "expected_result": {"text": "expected"}}]))["task"]
    await service.evolve_write_file(task["task_id"], "tool.py", "async def handle(command,args):\n    return {}\n")
    monkeypatch.setattr("agentkit.tools.self_evolve.self_evolve.GeneratedCapabilityService.invoke", AsyncMock(return_value={"text": "wrong"}))
    result = await service.evolve_validate(task["task_id"])
    assert not result["ok"]
    assert "expected" in result["errors"][0]
    with pytest.raises(ValueError, match="pass validation"):
        await service.evolve_publish(task["task_id"])


@pytest.mark.asyncio
async def test_failed_build_is_feedback_and_never_a_validation_pass(service, monkeypatch):
    task_id = await create(service)
    check = AsyncMock(side_effect=PermissionError("sandbox unavailable"))
    monkeypatch.setattr("agentkit.security.process_sandbox.SandboxedProcessRunner.run_async", check)
    result = await service.evolve_run_check(task_id, ["npm", "test"])
    assert not result["ok"] and "sandbox" in result["error"]
    task = service._get_task_or_raise(task_id)
    assert task["status"] == "draft" and task["checks"][-1]["ok"] is False
    check.assert_awaited_once()
    assert "validated_digest" not in task


@pytest.mark.asyncio
async def test_oldest_retained_checkpoint_can_be_restored_at_capacity(service):
    task_id = await create(service)
    for i in range(22):
        await service.evolve_write_file(task_id, "index.html", f"<h1>{i}</h1>")
    task = service._get_task_or_raise(task_id)
    assert len(task["checkpoints"]) == 20
    checkpoint = task["checkpoints"][0]["checkpoint_id"]
    source = service.staging_root.parent / "checkpoints" / task_id / checkpoint / "index.html"
    expected = source.read_text(encoding="utf-8")
    await service.evolve_restore(task_id, checkpoint)
    assert (service._task_root(task_id) / "index.html").read_text(encoding="utf-8") == expected


@pytest.mark.asyncio
async def test_canvas_state_write_failure_rolls_back_and_results_cannot_mutate_authority(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(APP, encoding="utf-8")
    controller = EnvironmentController(str(tmp_path))
    await controller.initialize()
    row = (await controller.execute("register", {"name": "App"})).result
    params = {"environment_id": row["environment_id"]}
    def fail():
        raise OSError("disk unavailable")
    original_save = controller._save
    monkeypatch.setattr(controller, "_save", fail)
    out = await controller.execute("state_set", {**params, "expected_revision": 0, "value": {"text": "unsaved"}})
    assert not out.success
    assert (await controller.execute("state_get", params)).result == {"revision": 0, "value": {}}
    monkeypatch.setattr(controller, "_save", original_save)
    value = {"text": "saved"}
    result = (await controller.execute("state_set", {**params, "expected_revision": 0, "value": value})).result
    value["text"] = "changed by caller"
    result["value"]["text"] = "changed by result consumer"
    read = (await controller.execute("state_get", params)).result
    assert read["value"] == {"text": "saved"}
    read["value"]["text"] = "changed by reader"
    assert (await controller.execute("state_get", params)).result["value"] == {"text": "saved"}
