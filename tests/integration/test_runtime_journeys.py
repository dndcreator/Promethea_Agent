"""Real Runtime, standard tools and disk state; no mocked successful Conversation."""
import json

import pytest

from gateway.protocol import RequestType
from gateway.capability_service import ToolInvocationContext
from gateway.tools.spec import SideEffectLevel
from tests.support.runtime import ScriptedModel, finish_from_observation, runtime_at


def write_action(path="reports/result.md", content="Revenue: 41\nCost: 9\nNet: 32\n"):
    return {"action": "tool_call", "id": "write-1", "tool_name": "workspace.write_file", "args": {"path": path, "content": content}}


@pytest.mark.asyncio
async def test_actual_artifact_readback_history_and_restart(tmp_path):
    model = ScriptedModel([write_action(), {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "reports/result.md"}}, finish_from_observation])
    host = runtime_at(tmp_path, model)
    response = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Write and verify the supplied report", "session_id": "report"}, user_id="alice")
    assert response.ok, response.error
    assert response.payload["status"] == "success", response.payload
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="report")
    from pathlib import Path
    artifact = Path(handle.root_path) / "reports/result.md"
    assert artifact.read_text(encoding="utf-8") == write_action()["args"]["content"]
    assert "32" in response.payload["response"]
    history = host.message_manager.get_messages("report", user_id="alice")
    assert history[-1]["content"] == response.payload["response"]
    assert "workspace.write_file" in json.dumps(model.calls[0]) and "input_schema" in json.dumps(model.calls[0])
    restored = runtime_at(tmp_path, ScriptedModel([]))
    assert restored.message_manager.get_messages("report", user_id="alice") == history
    assert restored.message_manager.get_messages("report", user_id="bob") == []
    with pytest.raises(FileNotFoundError):
        await restored.capability_service.call_tool("workspace.read_file", {"path": "reports/result.md"}, ctx=ToolInvocationContext(user_id="bob", session_id="report"))


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_sensitive_artifact_requires_real_approval_and_never_fake_success(tmp_path, decision):
    model = ScriptedModel([write_action(), finish_from_observation])
    host = runtime_at(tmp_path, model)
    spec = host.capability_service.tool_registry.resolve(tool_name="workspace.write_file", params={})
    # Exercise the same standard writer behind an explicitly higher-risk policy.
    spec.side_effect_level = SideEffectLevel.EXTERNAL_WRITE
    first = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Publish the report", "session_id": "report"}, user_id="alice")
    assert first.ok and first.payload["status"] == "needs_confirmation", first.payload
    from pathlib import Path
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="report")
    artifact = Path(handle.root_path) / "reports/result.md"
    assert not artifact.exists()
    result = await host.handle_http_request(method=RequestType.CHAT_CONFIRM, params={"session_id": "report", "tool_call_id": first.payload["tool_call_id"], "action": decision}, user_id="alice")
    assert result.ok and result.payload["status"] == "success", result.payload
    assert artifact.exists() is (decision == "approve")
    assert host.message_manager.get_pending_confirmation("report", user_id="alice") is None
    if decision == "approve":
        assert artifact.read_text(encoding="utf-8") == write_action()["args"]["content"]
    else:
        assert "USER_DECLINED" in json.dumps(model.calls[-1])
