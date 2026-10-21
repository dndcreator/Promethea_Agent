import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentkit.security.approval import approval_scope, call_is_approved
from agentkit.security.sandbox import SandboxPolicy
from gateway.action.model_action import InvalidModelAction, parse_model_action
from gateway.action.service import ActionService
from gateway.capability_service import CapabilityService, ToolInvocationContext, ToolConfirmationRequiredError
from gateway.chat_gateway_handler import handle_chat_confirm
from gateway.workspace_service import WorkspaceService


class _Core:
    def __init__(self, responses):
        self.responses = list(responses)

    async def call_llm(self, _messages, **_kwargs):
        return {"status": "success", "content": self.responses.pop(0)}


def _batch_action():
    return json.dumps(
        {
            "action": "tool_calls",
            "calls": [
                {"id": "a", "tool_name": "execute_command", "args": {"command": "one"}},
                {"id": "b", "tool_name": "execute_command", "args": {"command": "two"}},
            ],
        }
    )


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
    executor = AsyncMock(return_value={"ok": True})
    service = ActionService(conversation_core=_Core([_batch_action(), '{"action":"answer","content":"done"}']))
    pending = await service.run_action(
        goal="batch",
        messages=[{"role": "user", "content": "batch"}],
        tool_executor=executor,
        confirmation_resolver=lambda *_: True,
        budget=3,
    )
    second = await service.resume_action(
        pending=pending,
        approved_call_id="a",
        user_config=None,
        session_id="s",
        user_id="u",
        run_context=None,
        tool_executor=executor,
        confirmation_resolver=lambda *_: True,
    )
    assert second["status"] == "needs_confirmation"
    assert second["tool_call_id"] == "b"
    executor.assert_not_awaited()

    result = await service.resume_action(
        pending=second,
        approved_call_id="b",
        user_config=None,
        session_id="s",
        user_id="u",
        run_context=None,
        tool_executor=executor,
        confirmation_resolver=lambda *_: True,
    )
    assert result["status"] == "success"
    assert executor.await_count == 2
    assert not call_is_approved()


def test_duplicate_ids_cannot_extend_approval_to_another_call():
    with pytest.raises(InvalidModelAction, match="unique"):
        parse_model_action(
            '{"action":"tool_calls","calls":['
            '{"id":"same","tool_name":"a","args":{}},'
            '{"id":"same","tool_name":"b","args":{}}]}'
        )


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
        with pytest.raises(ToolConfirmationRequiredError):
            await service.call_tool(Tool.tool_id, {"value": 2, "approved": True})
    assert same["approved"] is True


@pytest.mark.asyncio
async def test_runtime_confirmation_comes_from_tool_registry_policy():
    capabilities = CapabilityService()

    class Tool:
        tool_id = name = "custom.side_effect"
        description = "A deliberately neutral description"
        side_effect_level = "external_write"

        async def invoke(self, args, ctx):
            return {"ok": True}

    capabilities.register_tool(Tool())
    pending = await ActionService(
        conversation_core=_Core(['{"action":"tool_call","id":"custom","tool_name":"custom.side_effect","args":{"value":1}}'])
    ).run_action(
        goal="side effect",
        messages=[{"role": "user", "content": "side effect"}],
        tool_executor=AsyncMock(return_value={"ok": True}),
        confirmation_resolver=capabilities.requires_confirmation,
    )
    assert pending["status"] == "needs_confirmation"
    assert pending["tool_call_id"] == "custom"


@pytest.mark.asyncio
async def test_confirm_handler_preserves_batch_consent_and_rejects_replay():
    pending = {"tool_call_id": "a", "turn_id": "turn", "status": "needs_confirmation", "reasoning_tree_id": "tree"}

    def store(_session, data, **_kwargs):
        nonlocal pending
        pending = data

    def clear(*_args, **_kwargs):
        nonlocal pending
        pending = None

    entered, finish = asyncio.Event(), asyncio.Event()

    async def resume_action(**kwargs):
        assert kwargs["run_context"].conversation_turn_id == "turn"
        if kwargs["approved_call_id"] == "a":
            return {"status": "needs_confirmation", "tool_call_id": "b", "tool_name": "write", "args": {}, "approved_call_ids": ["a"]}
        entered.set()
        await finish.wait()
        return {"status": "success", "content": "done"}

    server = SimpleNamespace(
        message_manager=SimpleNamespace(
            get_pending_confirmation=lambda *a, **k: pending,
            set_pending_confirmation=store,
            clear_pending_confirmation=clear,
            commit_turn=Mock(return_value=True),
            add_message=Mock(),
        ),
        conversation_service=SimpleNamespace(resume_action=resume_action),
        config_service=None,
        _resolve_request_user_id=lambda *a: "user",
        _build_run_context=lambda **k: SimpleNamespace(trace_id="trace"),
        _execute_tool_for_chat=AsyncMock(),
    )
    connection = SimpleNamespace(connection_id="connection")
    first = await handle_chat_confirm(
        server,
        connection,
        SimpleNamespace(id="r1", params={"session_id": "s", "tool_call_id": "a", "action": "approve"}),
    )
    assert first.ok and pending["tool_call_id"] == "b"
    request = SimpleNamespace(id="r2", params={"session_id": "s", "tool_call_id": "b", "action": "approve"})
    running = asyncio.create_task(handle_chat_confirm(server, connection, request))
    await entered.wait()
    try:
        replay = await handle_chat_confirm(server, connection, request)
        assert not replay.ok
    finally:
        finish.set()
    assert (await running).ok
    assert server.message_manager.commit_turn.call_args.kwargs["reasoning_tree_id"] == "tree"


@pytest.mark.asyncio
async def test_confirmation_failure_never_commits_an_assistant_reply():
    manager = SimpleNamespace(
        get_pending_confirmation=lambda *a, **k: {"tool_call_id": "call", "turn_id": "turn"},
        clear_pending_confirmation=Mock(),
        abort_turn=Mock(),
        commit_turn=Mock(),
        add_message=Mock(),
    )
    server = SimpleNamespace(
        message_manager=manager,
        conversation_service=SimpleNamespace(resume_action=AsyncMock(return_value={
            "status": "error", "content": "", "error": {"message": "provider unavailable"},
        })),
        config_service=None,
        _resolve_request_user_id=lambda *a: "user",
        _build_run_context=lambda **k: SimpleNamespace(trace_id="trace"),
        _execute_tool_for_chat=AsyncMock(),
    )
    response = await handle_chat_confirm(
        server, SimpleNamespace(connection_id="connection"),
        SimpleNamespace(id="request", params={"session_id": "s", "tool_call_id": "call", "action": "approve"}),
    )
    assert not response.ok
    manager.commit_turn.assert_not_called()
    manager.add_message.assert_not_called()
    manager.abort_turn.assert_called_once_with(
        "s", "turn", user_id="user", error={"message": "provider unavailable"},
        reasoning_tree_id=None, reasoning_steps=None,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process sandbox")
async def test_native_approved_image_workflow_preserves_original(monkeypatch, tmp_path):
    import win32api
    import win32security
    from PIL import Image
    from computer.filesystem import FileSystemController
    from agentkit.tools.standard.code_tools import CodeRunPythonTool

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
    capabilities = CapabilityService()
    capabilities.workspace_service = workspaces
    capabilities.register_tool(CodeRunPythonTool(workspace_service=workspaces))
    ctx = ToolInvocationContext(user_id="u", session_id="s")
    code = "from PIL import Image\nImage.open('input.png').resize((40,30)).save('output.png')"

    async def executor(name, args):
        return await capabilities.call_tool(name, args, ctx=ctx)

    service = ActionService(conversation_core=_Core([
        json.dumps({"action": "tool_call", "id": "image", "tool_name": "code.run_python", "args": {"code": code}}),
        '{"action":"answer","content":"done"}',
    ]))
    pending = await service.run_action(
        goal="resize image",
        messages=[{"role": "user", "content": "resize image"}],
        tool_executor=executor,
        confirmation_resolver=capabilities.requires_confirmation,
    )
    assert pending["status"] == "needs_confirmation"
    result = await service.resume_action(
        pending=pending,
        approved_call_id="image",
        user_config=None,
        session_id="s",
        user_id="u",
        run_context=None,
        tool_executor=executor,
        confirmation_resolver=capabilities.requires_confirmation,
    )
    assert result["status"] == "success"
    with Image.open(Path(handle.root_path) / "output.png") as image:
        assert image.size == (40, 30)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert not call_is_approved()
