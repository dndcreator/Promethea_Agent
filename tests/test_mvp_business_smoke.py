from pathlib import Path

import pytest

from gateway.conversation_service import ConversationService
from gateway.protocol import ConversationRunInput, RequestType
from gateway.server import GatewayServer
from gateway.tool_service import ToolService
from gateway.workflow_engine import WorkflowEngine
from gateway.workflow_models import WorkflowDefinition, WorkflowStep
from gateway.workspace_service import WorkspaceService


class _DummyCore:
    async def run_chat_loop(self, messages, user_config=None, session_id=None, user_id=None, tool_executor=None):
        _ = (messages, user_config, session_id, user_id, tool_executor)
        return {"status": "success", "content": "ok"}

    async def call_llm(self, messages, user_config=None, user_id=None):
        _ = (messages, user_config, user_id)
        return {"content": "{\"recall\": false}"}


class _EchoTool:
    tool_id = "utils.echo"
    name = "utils.echo"
    description = "Echo input text."

    async def invoke(self, args, ctx=None):
        _ = ctx
        return {"echo": str((args or {}).get("text") or "")}


@pytest.mark.asyncio
async def test_business_smoke_conversation_returns_capability_state():
    service = ConversationService(conversation_core=_DummyCore(), event_emitter=None)
    out = await service.run_conversation(
        ConversationRunInput(user_message="hello", session_id="s1", user_id="u1")
    )
    assert out.status == "success"
    capability = out.raw.get("capability_state") or {}
    assert isinstance(capability, dict)
    assert "memory" in capability
    assert "reasoning" in capability
    assert "tools" in capability


@pytest.mark.asyncio
async def test_business_smoke_tool_catalog_has_callable_now():
    service = ToolService(event_emitter=None)
    service.register_tool(_EchoTool())
    catalog = await service.get_tool_catalog()
    row = next((x for x in catalog if x.get("service_name") == "utils.echo"), None)
    assert row is not None
    assert "callable_now" in row
    assert row["callable_now"] is True
    assert "requires_confirmation" in row


@pytest.mark.asyncio
async def test_business_smoke_gateway_http_tool_flow():
    server = GatewayServer()
    server.tool_service = ToolService(event_emitter=None)
    server.tool_service.register_tool(_EchoTool())

    listed = await server.handle_http_request(
        method=RequestType.TOOLS_LIST,
        params={"requested_mode": "react_tot"},
        user_id="u1",
    )
    assert listed.ok is True
    assert listed.payload["catalog_total"] >= 1
    assert listed.payload["catalog_callable_now"] >= 1

    called = await server.handle_http_request(
        method=RequestType.TOOL_CALL,
        params={"tool_name": "utils.echo", "params": {"text": "from-http-flow"}},
        user_id="u1",
    )
    assert called.ok is True
    assert (called.payload.get("result") or {}).get("echo") == "from-http-flow"


def test_business_smoke_workflow_runs_tool_step(tmp_path: Path):
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    tool_service = ToolService(event_emitter=None)
    tool_service.register_tool(_EchoTool())
    engine = WorkflowEngine(workspace_service=ws, tool_service=tool_service)
    definition = WorkflowDefinition(
        workflow_id="wf.business.smoke",
        workflow_type="parallel",
        name="Business Smoke",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="t1",
                step_type="tool_step",
                name="Echo A",
                inputs={"tool_name": "utils.echo", "args": {"text": "a"}},
            ),
            WorkflowStep(
                step_id="t2",
                step_type="tool_step",
                name="Echo B",
                inputs={"tool_name": "utils.echo", "args": {"text": "b"}},
            ),
            WorkflowStep(
                step_id="join",
                step_type="artifact_step",
                name="Write Join",
                depends_on=["t1", "t2"],
                inputs={"path": "outputs/join.md", "content": "joined"},
            ),
        ],
    )
    engine.define_workflow(definition)
    run = engine.start_workflow(
        workflow_id="wf.business.smoke",
        session_id="s1",
        user_id="u1",
        workspace_id="w1",
    )
    assert run.status == "completed"
    assert run.run_metadata.get("workflow_type") == "parallel"
    assert run.run_metadata.get("scheduler_mode") == "dependency_batch"
    assert any((s.outputs.get("result") or {}).get("echo") == "a" for s in run.steps if s.step_id == "t1")
    assert any((s.outputs.get("result") or {}).get("echo") == "b" for s in run.steps if s.step_id == "t2")
    handle = ws.resolve_workspace_handle(user_id="u1", workspace_id="w1")
    assert (Path(handle.root_path) / "outputs" / "join.md").exists()
