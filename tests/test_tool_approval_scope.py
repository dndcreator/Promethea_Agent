import asyncio
import hashlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentkit.mcp.tool_call import ToolConfirmationRequired, execute_tool_calls_detailed
from agentkit.security.approval import approval_scope, call_is_approved
from agentkit.security.sandbox import SandboxPolicy
from gateway.chat_gateway_handler import handle_chat_confirm
from gateway.capability_service import ToolInvocationContext, CapabilityService
from gateway.workspace_service import WorkspaceService


def tool_call(identifier="one", name="execute_command", **args):
    return {"id": identifier, "name": name, "args": args}


def test_approval_mode_is_limited_to_invocation_and_does_not_override_denial():
    policy = SandboxPolicy(command_mode="approval", desktop_mode="approval")
    assert not policy.check_command("python -V").allowed
    assert not policy.check_desktop_action("click").allowed
    with approval_scope("test", {}, confirmed=True):
        assert policy.check_command("python -V").allowed
        assert policy.check_desktop_action("click").allowed
        assert not SandboxPolicy(command_mode="deny").check_command("python -V").allowed
        assert not SandboxPolicy(desktop_mode="observe_only").check_desktop_action("click").allowed
    assert not policy.check_command("python -V").allowed


@pytest.mark.asyncio
async def test_approval_expires_in_inherited_background_task():
    release = asyncio.Event()

    async def child():
        await release.wait()
        return call_is_approved()

    with approval_scope("test", {}, confirmed=True):
        task = asyncio.create_task(child())
    release.set()
    assert await task is False


@pytest.mark.asyncio
async def test_batch_approvals_accumulate_without_executing_early():
    calls = [tool_call("a"), tool_call("b")]
    executor = AsyncMock(return_value={"ok": True})
    resolver = lambda _name, _args: True
    with pytest.raises(ToolConfirmationRequired) as first:
        await execute_tool_calls_detailed(calls, tool_executor=executor, confirmation_resolver=resolver)
    with pytest.raises(ToolConfirmationRequired) as second:
        await execute_tool_calls_detailed(
            first.value.all_tool_calls,
            tool_executor=executor,
            confirmation_resolver=resolver,
            approved_call_ids={"a"},
        )
    assert second.value.approved_call_ids == {"a"}
    assert second.value.tool_call_id == "b"
    executor.assert_not_awaited()
    result = await execute_tool_calls_detailed(
        second.value.all_tool_calls,
        tool_executor=executor,
        confirmation_resolver=resolver,
        approved_call_ids=second.value.approved_call_ids | {"b"},
    )
    assert all(row.ok for row in result)
    assert executor.await_count == 2
    assert not call_is_approved()


@pytest.mark.asyncio
async def test_duplicate_ids_cannot_extend_approval_to_another_call():
    with pytest.raises(ValueError, match="unique"):
        await execute_tool_calls_detailed(
            [tool_call(), tool_call(command="other")],
            tool_executor=AsyncMock(),
            confirmation_resolver=lambda _name, _args: False,
            approved_call_ids={"one"},
        )


@pytest.mark.asyncio
async def test_confirmation_keeps_snapshot_of_reviewed_arguments():
    calls = [tool_call(command="python -V")]
    with pytest.raises(ToolConfirmationRequired) as confirmation:
        await execute_tool_calls_detailed(
            calls,
            tool_executor=AsyncMock(),
            confirmation_resolver=lambda _name, _args: True,
        )
    calls[0]["args"]["command"] = "changed"
    assert confirmation.value.all_tool_calls[0]["args"]["command"] == "python -V"


@pytest.mark.asyncio
async def test_capability_service_does_not_transfer_consent_to_changed_arguments():
    service = CapabilityService()

    class Tool:
        tool_id = name = "test.consent"
        description = "Inspect consent"

        async def invoke(self, args, ctx):
            return {"approved": call_is_approved()}

    service.register_tool(Tool())
    with approval_scope(Tool.tool_id, {"value": 1}, confirmed=True):
        same = await service.call_tool(Tool.tool_id, {"value": 1})
        changed = await service.call_tool(Tool.tool_id, {"value": 2, "approved": True})
    assert same["approved"] is True
    assert changed["approved"] is False


@pytest.mark.asyncio
async def test_runtime_confirmation_comes_from_tool_registry_policy():
    service = CapabilityService()

    class Tool:
        tool_id = name = "custom.side_effect"
        description = "A deliberately neutral description"
        side_effect_level = "external_write"

        async def invoke(self, args, ctx):
            return {"ok": True}

    service.register_tool(Tool())
    calls = [tool_call("custom", Tool.tool_id, value=1)]
    with pytest.raises(ToolConfirmationRequired):
        await execute_tool_calls_detailed(
            calls,
            tool_executor=AsyncMock(return_value={"ok": True}),
            confirmation_resolver=service.requires_confirmation,
        )


@pytest.mark.asyncio
async def test_confirm_handler_preserves_batch_consent_and_rejects_replay():
    calls = [tool_call("a"), tool_call("b")]
    pending = {"tool_call_id": "a", "pending_tool_calls": calls, "current_messages": []}

    def store(session, data, **kwargs):
        nonlocal pending
        pending = data

    def clear(*args, **kwargs):
        nonlocal pending
        pending = None

    entered, finish = asyncio.Event(), asyncio.Event()

    async def execute(*args, **kwargs):
        assert call_is_approved()
        entered.set()
        await finish.wait()
        return {"ok": True}

    server = SimpleNamespace(
        message_manager=SimpleNamespace(get_pending_confirmation=lambda *a, **k: pending,
                                        set_pending_confirmation=store, clear_pending_confirmation=clear,
                                        add_message=Mock()),
        conversation_service=SimpleNamespace(run_conversation=AsyncMock(return_value={"status": "success", "content": "done"})),
        capability_service=SimpleNamespace(requires_confirmation=lambda *_args, **_kwargs: True),
        config_service=None, mcp_manager=object(),
        _resolve_request_user_id=lambda *a: "user",
        _build_run_context=lambda **k: SimpleNamespace(trace_id="trace"),
        _execute_tool_for_chat=execute, _emit_gateway_event=AsyncMock(),
    )
    connection = SimpleNamespace(connection_id="connection")
    request = SimpleNamespace(id="r1", params={"session_id": "s", "tool_call_id": "a", "action": "approve"})
    first = await handle_chat_confirm(server, connection, request)
    assert first.ok
    assert pending["tool_call_id"] == "b"
    assert pending["approved_call_ids"] == ["a"]
    request = SimpleNamespace(id="r2", params={"session_id": "s", "tool_call_id": "b", "action": "approve"})
    running = asyncio.create_task(handle_chat_confirm(server, connection, request))
    await entered.wait()
    try:
        replay = await handle_chat_confirm(server, connection, request)
        assert not replay.ok
    finally:
        finish.set()
    assert (await running).ok


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process sandbox")
async def test_native_approved_image_workflow_preserves_original(monkeypatch, tmp_path):
    import win32api
    import win32security
    from PIL import Image
    from computer.filesystem import FileSystemController
    from gateway.official_tools.code_tools import CodeRunPythonTool

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        if win32security.IsTokenRestricted(token):
            pytest.skip("requires non-restricted parent test process")
    finally:
        token.Close()
    monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy())
    original = tmp_path / "original.png"
    Image.new("RGB", (80, 60), "red").save(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    workspaces = WorkspaceService(base_dir=str(tmp_path / "workspaces"))
    handle = workspaces.resolve_workspace_handle(user_id="u", workspace_id="s")
    filesystem = FileSystemController(workspace_root=handle.root_path)
    filesystem.locations.register("input", lambda: tmp_path, host_readable=True)
    await filesystem.initialize()
    assert (await filesystem.execute("copy", {"src": str(original), "dst": "input.png"})).success
    service = CapabilityService()
    service.workspace_service = workspaces
    service.register_tool(CodeRunPythonTool(workspace_service=workspaces))
    ctx = ToolInvocationContext(user_id="u", session_id="s")
    code = "from PIL import Image\nImage.open('input.png').resize((40,30)).save('output.png')\nprint('created output.png')"
    calls = [tool_call("image", "code.run_python", code=code)]

    async def executor(name, args):
        return await service.call_tool(name, args, ctx=ctx)

    with pytest.raises(ToolConfirmationRequired):
        await execute_tool_calls_detailed(
            calls,
            tool_executor=executor,
            confirmation_resolver=service.requires_confirmation,
        )
    results = await execute_tool_calls_detailed(
        calls,
        tool_executor=executor,
        approved_call_ids={"image"},
        confirmation_resolver=service.requires_confirmation,
    )
    assert results[0].ok, results[0]
    from pathlib import Path

    with Image.open(Path(handle.root_path) / "output.png") as image:
        assert image.size == (40, 30)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert not call_is_approved()
