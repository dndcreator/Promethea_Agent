"""Real publish/hot-registration journey; model choices and fixture approvals are scripted.

This is execution acceptance, not evidence that a live model invents a useful tool.
No network, external account, product configuration or Core file is modified.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from agentkit.security.sandbox import SandboxPolicy
from gateway.capability_service import ToolInvocationContext
from tests.support.runtime import ScriptedModel, goal_context, observation_fact, runtime_at


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="actual native Windows process-sandbox acceptance")
async def test_missing_capability_can_be_authored_published_and_used_in_same_conversation(tmp_path, monkeypatch):
    import win32api
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    if win32security.IsTokenRestricted(token):
        pytest.skip("already-restricted runner cannot create another restricted token")
    source_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY",
                        SandboxPolicy(command_mode="allowlist", allowed_commands=["python", sys.executable]))
    manifest_dir = tmp_path / "bundled-authoring"
    manifest_dir.mkdir()
    shutil.copyfile(source_root / "agentkit/tools/self_evolve/agent-manifest.json", manifest_dir / "agent-manifest.json")
    core_file = tmp_path / "gateway/core_sentinel.py"
    core_file.parent.mkdir()
    core_file.write_text("CORE-UNCHANGED\n", encoding="utf-8")
    state = {}
    actor = "self_evolve."

    def discover_authoring(messages):
        fact = observation_fact(messages)
        assert fact["result"]["candidate_count"] == 0
        assert fact["result"]["task_feasibility"] == "not_assessed"
        assert "software" in fact["result"]["available_capability_groups"]
        return {"action": "capability_request", "objective": "Find capability-authoring tools",
                "required_capabilities": ["software.tools.create"], "max_side_effect": "privileged_host_action"}

    def create(messages):
        candidates = observation_fact(messages)["result"]["candidates"]
        assert actor + "evolve_create_task" in {row["name"] for row in candidates}
        return {"action": "tool_call", "tool_name": actor + "evolve_create_task", "args": {
            "goal": "Create a reusable text reversal capability and deliver its real output",
            "capability_id": "text_reverse", "version": "1.0.0", "description": "Reverse a supplied string",
            "commands": [{"command": "reverse_text", "description": "Reverse text", "provides": ["text.reverse"],
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                "outputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                "test_args": {"text": "abc"}, "expected_result": {"text": "cba"}}]}}

    def write_source(messages):
        state["task_id"] = observation_fact(messages)["result"]["task"]["task_id"]
        return {"action": "tool_call", "tool_name": actor + "evolve_write_file", "args": {
            "task_id": state["task_id"], "path": "tool.py",
            "content": "async def handle(command, args):\n    assert command == 'reverse_text'\n    return {'text': args['text'][::-1]}\n"}}

    def lifecycle(command):
        def propose(messages):
            fact = observation_fact(messages)
            assert fact["status"] == "completed", fact
            if command == "evolve_publish":
                assert fact["result"]["ok"], fact
            return {"action": "tool_call", "tool_name": actor + command, "args": {"task_id": state["task_id"]}}
        return propose

    def resolve_published(messages):
        fact = observation_fact(messages)
        assert fact["status"] == "completed", fact
        published = fact["result"]
        assert published["registered"]
        state["tool_id"] = published["tool_ids"][0]
        tool_message = next(row["content"] for row in messages if row.get("role") == "system" and row["content"].startswith("Runtime capabilities:"))
        assert state["tool_id"] in tool_message, "the same model loop must see the updated Registry"
        return {"action": "capability_request", "objective": "Invoke the newly available text reversal",
                "required_capabilities": ["text.reverse"], "max_side_effect": "privileged_host_action"}

    def invoke_published(messages):
        resolved = observation_fact(messages)["result"]
        candidate = next(row for row in resolved["candidates"] if row["name"] == state["tool_id"])
        assert candidate["input_schema"]["required"] == ["text"]
        assert candidate["requires_confirmation"]
        return {"action": "tool_call", "tool_name": state["tool_id"], "args": {"text": "ORCHID-29"}}

    def deliver(messages):
        result = observation_fact(messages)["result"]
        assert result == {"text": "92-DIHCRO"}
        return {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "result.txt", "content": result["text"]}}

    def finish(messages):
        fact = observation_fact(messages)
        return {"action": "answer", "content": "The generated tool's verified output is in result.txt", "gap_update": {
            "revision": goal_context(messages)["revision"], "updates": [{"id": "deliver", "state": "resolved", "evidence_refs": [fact["observation_id"]]}]}}

    model = ScriptedModel([
        {"action": "capability_request", "objective": "Reverse text using a reusable capability", "required_capabilities": ["text.reverse"],
         "gap_update": {"revision": 0, "create": [{"id": "deliver", "kind": "achievement", "requirement": "Deliver and read back the generated text result",
             "check": {"tool_name": "workspace.read_file", "pointer": "/content", "expected": "92-DIHCRO"}}]}},
        discover_authoring, create, write_source, lifecycle("evolve_validate"), lifecycle("evolve_publish"),
        resolve_published, invoke_published, deliver,
        {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "result.txt"}}, finish,
    ])
    host = runtime_at(tmp_path, model)
    host.message_manager.create_session("s", "alice")
    service = host.capability_service
    service.reload_discovered_tools([str(manifest_dir)], reload_modules=False)
    config = deepcopy(host.config_service.get_merged_config("alice"))
    config["self_evolve"]["enabled"] = True
    context = SimpleNamespace(user_id="alice", session_id="s")

    async def execute(name, args):
        result = await service.call_tool(name, args, run_context=context, user_config=config,
            ctx=ToolInvocationContext(user_id="alice", session_id="s", metadata={"run_context": context, "user_config": config}))
        state.setdefault("tool_results", []).append({"tool_name": name, "result": result})
        return result

    out = await host.conversation_service.run_chat_loop([{"role": "user", "content": "Create and use a reusable reversal capability; deliver its actual output"}],
        user_id="alice", session_id="s", user_config=config, run_context=context, tool_executor=execute, max_recursion=20)
    approved = []
    while out["status"] == "needs_confirmation":
        assert len(approved) < 3
        name = out["tool_name"]
        assert name in {actor + "evolve_validate", actor + "evolve_publish", state.get("tool_id")}
        approved.append(name)
        out = await host.conversation_service.resume_action(pending=out, approved_call_id=out["tool_call_id"],
            user_id="alice", session_id="s", user_config=config, run_context=context, tool_executor=execute)
    assert out["status"] == "success", json.dumps(state.get("tool_results"), ensure_ascii=True)
    assert approved == [actor + "evolve_validate", actor + "evolve_publish", state["tool_id"]]
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="s")
    assert (Path(handle.root_path) / "result.txt").read_text(encoding="utf-8") == "92-DIHCRO"
    assert core_file.read_text(encoding="utf-8") == "CORE-UNCHANGED\n"
    assert out["goal_progress"]["checks_passed"] == 1
    assert len(model.calls) == 11
    assert not service.inspect_capabilities([state["tool_id"]], run_context=SimpleNamespace(user_id="bob"), user_config=config)["items"][0]["registered"]
    private = await service.resolve_capability_intent({"required_capabilities": ["text.reverse"], "max_side_effect": "privileged_host_action"},
        run_context=SimpleNamespace(user_id="bob"), user_config=config)
    assert not private["candidates"]
    disabled = deepcopy(config)
    disabled["self_evolve"]["enabled"] = False
    result = await service.resolve_capability_intent({"required_capabilities": ["software.tools.create"], "max_side_effect": "privileged_host_action"},
        run_context=context, user_config=disabled)
    assert not result["candidates"] and result["unavailable_capabilities"] == ["software.tools.create"]
