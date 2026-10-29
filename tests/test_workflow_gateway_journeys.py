"""Gateway Workflow/batch integration; distinct from Action approval contracts."""
from pathlib import Path

import pytest

from gateway.protocol import RequestType
from gateway.server import GatewayServer
from gateway.capability_service import CapabilityService
from gateway.workflow_engine import WorkflowEngine
from gateway.workspace_service import WorkspaceService
from tests.support.tools import EchoTool as _EchoTool


@pytest.mark.asyncio
async def test_business_plus_workflow_pause_approve_resume(tmp_path: Path):
    server = GatewayServer()
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    engine = WorkflowEngine(
        workspace_service=workspace,
        storage_path=str(tmp_path / "workflow_state.json"),
    )
    server.workspace_service = workspace
    server.workflow_engine = engine

    defined = await server.handle_http_request(
        method=RequestType.WORKFLOW_DEFINE,
        params={
            "workflow_id": "wf.business.plus.approval",
            "name": "Business Plus Approval",
            "workflow_type": "linear",
            "steps": [
                {"step_id": "s1", "step_type": "approval_step", "name": "审批确认"},
                {
                    "step_id": "s2",
                    "step_type": "artifact_step",
                    "name": "写入产物",
                    "depends_on": ["s1"],
                    "inputs": {"path": "reports/approved.md", "content": "approved"},
                },
            ],
        },
        user_id="u_plus",
    )
    assert defined.ok is True

    started = await server.handle_http_request(
        method=RequestType.WORKFLOW_START,
        params={"workflow_id": "wf.business.plus.approval", "session_id": "s_plus", "workspace_id": "w_plus"},
        user_id="u_plus",
    )
    assert started.ok is True
    run_id = started.payload["run"]["workflow_run_id"]
    assert started.payload["run"]["status"] == "waiting_human"

    paused = await server.handle_http_request(
        method=RequestType.WORKFLOW_PAUSE,
        params={"workflow_run_id": run_id},
        user_id="u_plus",
    )
    assert paused.ok is True
    assert paused.payload["run"]["status"] == "paused"

    approved = await server.handle_http_request(
        method=RequestType.WORKFLOW_APPROVE_STEP,
        params={"workflow_run_id": run_id, "step_id": "s1"},
        user_id="u_plus",
    )
    assert approved.ok is True

    resumed = await server.handle_http_request(
        method=RequestType.WORKFLOW_RESUME,
        params={"workflow_run_id": run_id},
        user_id="u_plus",
    )
    assert resumed.ok is True
    assert resumed.payload["run"]["status"] == "completed"

    artifacts = await server.handle_http_request(
        method=RequestType.WORKSPACE_LIST_ARTIFACTS,
        params={"workspace_id": "w_plus", "session_id": "s_plus", "subdir": "reports"},
        user_id="u_plus",
    )
    assert artifacts.ok is True
    assert any(item.get("path") == "reports/approved.md" for item in (artifacts.payload.get("artifacts") or []))


@pytest.mark.asyncio
async def test_business_plus_batch_tool_and_workflow_visibility(tmp_path: Path):
    server = GatewayServer()
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspace"))
    engine = WorkflowEngine(
        workspace_service=workspace,
        storage_path=str(tmp_path / "workflow_state.json"),
    )
    tools = CapabilityService(event_emitter=None)
    tools.register_tool(_EchoTool())
    server.workspace_service = workspace
    server.workflow_engine = engine
    server.capability_service = tools

    define = await server.handle_http_request(
        method=RequestType.WORKFLOW_DEFINE,
        params={
            "workflow_id": "wf.plus.batch",
            "name": "Plus Batch",
            "workflow_type": "linear",
            "steps": [{"step_id": "s1", "step_type": "artifact_step", "name": "w", "inputs": {"path": "x.md", "content": "x"}}],
        },
        user_id="u_plus_batch",
    )
    assert define.ok is True

    batch = await server.handle_http_request(
        method=RequestType.BATCH,
        params={
            "requests": [
                {"method": RequestType.TOOLS_LIST.value, "params": {"requested_mode": "react_tot"}, "priority": 3},
                {"method": RequestType.TOOL_CALL.value, "params": {"tool_name": "utils.echo", "params": {"text": "plus"}}, "priority": 2},
                {"method": RequestType.WORKFLOW_LIST.value, "params": {"owner_user_id": "u_plus_batch"}, "priority": 1},
            ]
        },
        user_id="u_plus_batch",
    )
    assert batch.ok is True
    results = batch.payload.get("results") or []
    assert len(results) == 3
    by_method = {row["method"]: row for row in results}
    assert by_method[RequestType.TOOLS_LIST.value]["ok"] is True
    assert by_method[RequestType.TOOL_CALL.value]["ok"] is True
    assert by_method[RequestType.TOOL_CALL.value]["payload"]["result"]["echo"] == "plus"
    assert by_method[RequestType.WORKFLOW_LIST.value]["ok"] is True
    assert any(item.get("workflow_id") == "wf.plus.batch" for item in by_method[RequestType.WORKFLOW_LIST.value]["payload"]["workflows"])


