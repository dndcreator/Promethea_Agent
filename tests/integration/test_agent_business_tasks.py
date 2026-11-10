"""Real service journeys; scripted at the external model boundary only."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_evaluations import ASSETS
from tests.support.behavior import execute_case
from tests.support.evaluation import hard_checks
from tests.support.runtime import ScriptedModel, finish_from_observation, runtime_at


def call(name, **args):
    return {"action": "tool_call", "tool_name": name, "args": args}


@pytest.mark.asyncio
async def test_parent_child_deliver_and_verify_actual_artifact(tmp_path):
    corpus = json.loads((ASSETS / "behavior.json").read_text(encoding="utf-8"))
    case = next(case for case in corpus["cases"] if case["id"] == "delegate-artifact-readback")
    case["turns"][0] += " Parent-only marker: PRIVATE-PARENT-77; do not forward it."
    model = ScriptedModel([
        call("subagent.delegate", objective="Create result.txt containing NET=32", label="writer", run_in_background=False),
        call("workspace.write_file", path="result.txt", content="NET=32"), finish_from_observation,
        call("workspace.read_file", path="result.txt"), finish_from_observation,
    ])
    result = await execute_case(case, model, tmp_path)
    assert hard_checks(case, result) == [], result
    assert len(model.calls) == 5
    assert "PRIVATE-PARENT-77" in json.dumps(model.calls[0])
    assert "PRIVATE-PARENT-77" not in json.dumps(model.calls[1])
    assert (tmp_path / "workspaces/alice/evaluation/result.txt").read_text() == "NET=32"


@pytest.mark.asyncio
async def test_autonomous_goal_produces_work_without_chat_message(tmp_path):
    class Model(ScriptedModel):
        def __init__(self):
            super().__init__([
                call("workspace.read_file", path="report.txt"),
                call("workspace.write_file", path="plan.txt", content="Fix payment-17 before release"),
                finish_from_observation,
            ])
            self.budget = SimpleNamespace(calls=0)

        async def call_llm(self, *args, **kwargs):
            self.budget.calls += 1
            return await super().call_llm(*args, **kwargs)

    case = {"kind": "ambient", "enabled": True, "direction": "Inspect report.txt and prepare a local release plan; do not deploy.",
            "files": {"report.txt": "Blocker: payment-17 failed."}}
    result = await execute_case(case, Model(), tmp_path)
    assert result["status"] == "success", result
    assert (tmp_path / "workspaces/alice/evaluation/plan.txt").read_text() == "Fix payment-17 before release"
    assert result["evidence"]["tasks"]
    assert result["model_calls"] == 3


@pytest.mark.asyncio
async def test_reopened_memory_drives_agent_output_not_old_transcript(tmp_path):
    from memory.backends.sqlite_graph import SqliteGraphMemoryStore
    from memory.adapter import MemoryAdapter
    from gateway.memory_service import MemoryService
    from agentkit.tools.standard.memory_tools import MemoryGetContextTool
    from gateway.protocol import RequestType

    database = tmp_path / "memory.db"
    store = SqliteGraphMemoryStore(str(database))
    store.add_message(session_id="previous", role="user", content="My release code is ORCHID-29.", user_id="alice")
    store.add_message(session_id="previous", role="user", content="My release code is PRIVATE-BOB.", user_id="bob")
    store._conn.close()
    reopened = SqliteGraphMemoryStore(str(database))
    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled, adapter.store = True, reopened
    model = ScriptedModel([call("memory.get_context", query="release code"), finish_from_observation])
    host = runtime_at(tmp_path, model)
    service = MemoryService(memory_adapter=adapter, config_service=host.config_service)
    host.capability_service.register_tool(MemoryGetContextTool(memory_service=service))
    try:
        response = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Recall my release code from memory.", "session_id": "fresh"}, user_id="alice")
        assert response.ok and response.payload["status"] == "success", response
        answer = response.payload["response"]
        assert "ORCHID-29" in answer and "PRIVATE-BOB" not in answer
        assert "ORCHID-29" not in json.dumps(model.calls[0])
        assert "ORCHID-29" in json.dumps(model.calls[1])
    finally:
        reopened._conn.close()


@pytest.mark.asyncio
async def test_agent_canvas_feedback_edit_and_next_turn_share_actual_state(tmp_path):
    from computer.canvas_components import CanvasResourceRef, render_component_document
    from computer.environment import EnvironmentController
    from computer.execution_context import bind_workspace
    from computer.runtime import ComputerRuntime
    from agentkit.tools.standard.situation_tools import create_situation_tools
    from gateway.public_contracts import EnvironmentInteraction, SemanticUIFeedback, SemanticSurface
    from gateway.protocol import RequestType

    model = ScriptedModel([])
    host = runtime_at(tmp_path, model)
    runtime = ComputerRuntime({"environment": EnvironmentController})
    host.capability_service.computer_runtime = runtime
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="evaluation")
    document = {"version": "canvas.ui.v1", "title": "Quote", "language": "en", "initial_state": {"quantity": 2},
                "root": {"type": "stack", "id": "quote", "children": [{"type": "input", "id": "quantity", "label": "Quantity", "bind": "quantity", "input_type": "number"}]}}
    (Path(handle.root_path) / "index.html").write_text(render_component_document(document), encoding="utf-8")
    for tool in create_situation_tools(host.self_model_service):
        host.capability_service.register_tool(tool)
    try:
        with bind_workspace(handle):
            registered = await host.capability_service.execute_computer_action("environment", "register", {"name": "Quote"})
        resource = CanvasResourceRef(kind="canvas", id=registered.result["environment_id"], workspace_id="evaluation")
        source = await host.self_model_service.environment_sources.inspect("alice", resource)
        definition = source["semantics"]["definition_revision"]
        await host.self_model_service.environment.observe("alice", SemanticSurface(view="canvas", objects=[resource], active_component_id="quantity", definition_revision=definition))
        anchor = {"resource": resource.model_dump(), "component_id": "quantity", "definition_revision": definition}
        model.actions = iter([
            call("semantic_ui.present", expression_id="review", expected_revision=0, kind="choice", content="Review quantity?", choices=[{"id": "yes", "label": "Review"}], canvas_anchor=anchor),
            finish_from_observation,
        ])
        first = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Attach a review choice to this quantity.", "session_id": "evaluation"}, user_id="alice")
        assert first.ok and first.payload["status"] == "success", first
        await host.self_model_service.semantic_ui.feedback("alice", "review", SemanticUIFeedback(expected_revision=1, action="respond", choice_id="yes"))
        command = EnvironmentInteraction(resource=resource, interaction={"component_id": "quantity", "operation": "set", "value": 7, "expected_revision": 0, "definition_revision": definition})
        await host.self_model_service.environment_sources.interact("alice", command)
        model.actions = iter([call("environment.inspect", resource=resource.model_dump()), finish_from_observation])
        second = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Inspect the current quantity after my edit.", "session_id": "evaluation"}, user_id="alice")
        assert second.ok and second.payload["status"] == "success", second
        current = await host.self_model_service.environment_sources.inspect("alice", resource)
        assert next(component for component in current["semantics"]["components"] if component["component_id"] == "quantity")["value"] == 7
        assert host.self_model_service.semantic_ui.view("alice")["expressions"][0]["response"] == "yes"
        assert '7' in second.payload["response"]
    finally:
        await runtime.close()
