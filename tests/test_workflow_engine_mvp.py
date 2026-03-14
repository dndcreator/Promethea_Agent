from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer
from gateway.workspace_service import WorkspaceService
from gateway.workflow_engine import WorkflowEngine
from gateway.workflow_models import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_WAITING_HUMAN,
    STEP_STATUS_FAILED,
    STEP_STATUS_SUCCEEDED,
    WorkflowDefinition,
    WorkflowStep,
)


def _approval_definition(workflow_id: str = "wf.approval") -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name="Approval Flow",
        owner_user_id="u1",
        steps=[
            WorkflowStep(step_id="s1", step_type="reasoning_step", name="Plan"),
            WorkflowStep(step_id="s2", step_type="approval_step", name="Approve", requires_human_approval=True),
            WorkflowStep(
                step_id="s3",
                step_type="artifact_step",
                name="Write",
                inputs={"path": "outputs/final.md", "content": "done"},
            ),
        ],
    )


def _artifact_definition(workflow_id: str = "wf.artifact", *, path: str = "outputs/file.md") -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name="Artifact Flow",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="s1",
                step_type="artifact_step",
                name="Write",
                inputs={"path": path, "content": "artifact"},
            )
        ],
    )


def _engine(tmp_path: Path) -> tuple[WorkflowEngine, WorkspaceService]:
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    engine = WorkflowEngine(workspace_service=ws)
    return engine, ws


def test_workflow_definition_creation(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    definition = _approval_definition()
    saved = engine.define_workflow(definition)

    assert saved.workflow_id == "wf.approval"
    assert len(saved.steps) == 3


def test_workflow_run_state_flow_waits_for_approval(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_approval_definition())

    run = engine.start_workflow(workflow_id="wf.approval", session_id="s1", user_id="u1", workspace_id="w1")

    assert run.status == RUN_STATUS_WAITING_HUMAN
    assert run.current_step_id == "s2"
    assert run.steps[0].status == STEP_STATUS_SUCCEEDED


def test_linear_workflow_main_path_runs_to_completion(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_approval_definition())

    run = engine.start_workflow(workflow_id="wf.approval", session_id="s1", user_id="u1", workspace_id="w1")
    run = engine.approve_step(run.workflow_run_id, "s2", "u1")

    assert run.status == RUN_STATUS_COMPLETED
    assert run.steps[2].status == STEP_STATUS_SUCCEEDED


def test_checkpoint_creation(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_approval_definition())

    run = engine.start_workflow(workflow_id="wf.approval", session_id="s1", user_id="u1", workspace_id="w1")
    ckpts = engine.list_checkpoints(run.workflow_run_id)
    assert len(ckpts) >= 2


def test_pause_resume(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_approval_definition())

    run = engine.start_workflow(workflow_id="wf.approval", session_id="s1", user_id="u1", workspace_id="w1")
    paused = engine.pause_workflow(run.workflow_run_id)
    assert paused.status == RUN_STATUS_PAUSED

    engine.approve_step(run.workflow_run_id, "s2", "u1")
    resumed = engine.resume_workflow(run.workflow_run_id)
    assert resumed.status == RUN_STATUS_COMPLETED


def test_failed_step_retry(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_artifact_definition(path="../escape.md"))

    run = engine.start_workflow(workflow_id="wf.artifact", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_FAILED
    assert run.steps[0].status == STEP_STATUS_FAILED

    run.steps[0].inputs["path"] = "outputs/retry.md"
    retried = engine.retry_step(run.workflow_run_id, "s1")
    assert retried.status == RUN_STATUS_COMPLETED


def test_artifact_written_to_workspace(tmp_path: Path):
    engine, ws = _engine(tmp_path)
    engine.define_workflow(_artifact_definition(path="outputs/proof.md"))

    run = engine.start_workflow(workflow_id="wf.artifact", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_COMPLETED

    handle = ws.resolve_workspace_handle(user_id="u1", workspace_id="w1")
    target = Path(handle.root_path) / "outputs" / "proof.md"
    assert target.exists()


@pytest.mark.asyncio
async def test_gateway_workflow_handlers(tmp_path: Path):
    server = GatewayServer()
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    server.workspace_service = ws
    server.workflow_engine = WorkflowEngine(workspace_service=ws)

    connection = SimpleNamespace(connection_id="c1", identity=SimpleNamespace(device_id="u1"))

    define_req = RequestMessage(
        id="r1",
        method=RequestType.WORKFLOW_DEFINE,
        params={
            "workflow_id": "wf.api",
            "name": "API Flow",
            "steps": [
                {"step_id": "s1", "step_type": "artifact_step", "name": "Write", "inputs": {"path": "outputs/a.md", "content": "ok"}}
            ],
        },
    )
    define_res = await server._handle_workflow_define(connection, define_req)
    assert define_res.ok is True

    start_req = RequestMessage(
        id="r2",
        method=RequestType.WORKFLOW_START,
        params={"workflow_id": "wf.api", "session_id": "s1", "workspace_id": "w1", "user_id": "u1"},
    )
    start_res = await server._handle_workflow_start(connection, start_req)
    assert start_res.ok is True
    run_id = start_res.payload["run"]["workflow_run_id"]

    status_req = RequestMessage(
        id="r3",
        method=RequestType.WORKFLOW_STATUS,
        params={"workflow_run_id": run_id},
    )
    status_res = await server._handle_workflow_status(connection, status_req)
    assert status_res.ok is True
    assert status_res.payload["run"]["status"] == RUN_STATUS_COMPLETED
