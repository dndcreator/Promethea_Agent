"""Actual workspace repair/test/approval/restart; model decisions are scripted.

This verifies execution mechanics, not autonomous diagnosis quality. The known
fixture test is approved explicitly; partial host sandboxes are never auto-approved.
"""
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from agentkit.security.sandbox import SandboxPolicy
from agentkit.tools.standard.code_tools import CodeRunPythonTool
from agentkit.tools.standard.workspace_tools import WorkspaceReadFileTool, WorkspaceReplaceTextTool
from agentkit.tools.moirai.learning import MoiraiLearning
from config import config
from gateway.public_contracts import AmbientSettings, AmbientConfirmation
from gateway.workspace_service import WorkspaceService
from tests.support.runtime import ScriptedModel, observation_fact, goal_context
from tests.test_background_agents import drain
from tests.test_continuous_observation import host_at


def attach_workspace(root, conversation):
    workspace = WorkspaceService(base_dir=str(root / "workspaces"))
    conversation.capability_service.workspace_service = workspace
    for tool in (WorkspaceReadFileTool(workspace_service=workspace), WorkspaceReplaceTextTool(workspace_service=workspace),
                 CodeRunPythonTool(workspace_service=workspace)):
        conversation.capability_service.register_tool(tool)
    conversation.reasoning_service = SimpleNamespace(template_memory=SimpleNamespace(learning=MoiraiLearning(root / "learning")))
    return workspace.resolve_workspace_handle(user_id="alice", workspace_id="chat")


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="this acceptance exercises the native Windows runner")
async def test_repair_actual_python_code_approve_test_after_restart_and_record_evidence(tmp_path, monkeypatch):
    import win32api
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    if win32security.IsTokenRestricted(token):
        pytest.skip("already-restricted runner cannot create a second native restricted token")
    monkeypatch.setattr(config.moirai_learning, "distillation_enabled", False)
    policy = SandboxPolicy(command_mode="allowlist", allowed_commands=["python", sys.executable])
    monkeypatch.setattr("agentkit.tools.standard.code_tools.get_sandbox_policy", lambda: policy)
    code = "import runpy\nns=runpy.run_path('calculator.py')\nassert ns['add'](2,3)==5\nassert ns['add'](-2,3)==1\nprint('CHECK-OK-29')"

    def final(messages):
        fact = observation_fact(messages)
        return {"action": "answer", "content": "The isolated fix passed the actual regression test.", "evidence_refs": [fact["observation_id"]],
                "gap_update": {"revision": goal_context(messages)["revision"], "updates": [
                    {"id": "regression", "state": "resolved", "evidence_refs": [fact["observation_id"]]}]}}

    def propose_check(messages):
        return {"action": "tool_call", "tool_name": "code.run_python", "args": {"code": code},
                "gap_update": {"revision": goal_context(messages)["revision"],
                    "create": [{"id": "regression", "kind": "achievement", "requirement": "Both addition regression checks pass",
                                "check": {"tool_name": "code.run_python", "pointer": "/stdout", "expected": "CHECK-OK-29\r\n"}}]}}

    core = ScriptedModel([
        {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "calculator.py"}},
        {"action": "tool_call", "tool_name": "workspace.replace_text", "args": {"path": "calculator.py", "pattern": "return a - b", "replacement": "return a + b"}},
        propose_check, final])
    tasks, runtime, conversation, _, ambient, _, _, _ = host_at(tmp_path, core)
    handle = attach_workspace(tmp_path, conversation)
    project = Path(handle.root_path)
    (project / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Investigate and repair the isolated regression"))
        await drain(runtime)
        state = ambient.view("alice", "chat")
        assert state["status"] == "waiting_confirmation"
        assert state["pending"]["tool_name"] == "code.run_python"
        assert "return a + b" in (project / "calculator.py").read_text()
        pending = state["pending"]
        assert not conversation.reasoning_service.template_memory.learning.episodes("alice")
    finally:
        await runtime.shutdown()
    tasks, runtime, conversation, _, ambient, _, _, server = host_at(tmp_path, core)
    attach_workspace(tmp_path, conversation)
    try:
        assert ambient.view("alice", "chat")["pending"]["tool_call_id"] == pending["tool_call_id"]
        await ambient.confirm("alice", "chat", AmbientConfirmation(run_id=pending["run_id"], tool_call_id=pending["tool_call_id"], action="approve"))
        task = tasks.get_task(state["task_id"], user_id="alice")
        observations = server.event_emitter.event_log.query(user_id="alice", event_type="action.observation.committed", oldest_first=True)
        result = next(row["payload"] for row in observations if row["payload"].get("tool_name") == "code.run_python")
        assert result["ok"], result
        assert result["structured_result"]["returncode"] == 0
        assert result["structured_result"]["sandbox"]["backend"] == "windows-restricted-token"
        assert task["goal_gaps"]["gaps"][0]["support"] == "checked"
        learning = conversation.reasoning_service.template_memory.learning
        assert len(learning.episodes("alice")) == 1
        assert task["runs"][0]["status"] == "completed"
        output = Path(".tmp/continuous-code-maintenance")
        output.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / "calculator.py", output / "calculator.py")
        (output / "report.json").write_text(json.dumps({"task_id": task["task_id"], "test_result": result["structured_result"],
            "goal_progress": task["goal_gaps"], "process_restarted_before_approval": True, "learning_episodes": 1,
            "model": "scripted", "autonomous_diagnosis_verified": False}, indent=2), encoding="utf-8")
    finally:
        await runtime.shutdown()
