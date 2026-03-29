from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer
from gateway.tool_service import ToolService
from gateway.workspace_service import WorkspaceService
from gateway.workflow_engine import WorkflowEngine, WorkflowError
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


def _dag_artifact_definition(workflow_id: str = "wf.dag") -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        workflow_type="dag",
        name="DAG Artifact Flow",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="root",
                step_type="artifact_step",
                name="Root",
                inputs={"path": "outputs/root.md", "content": "root"},
            ),
            WorkflowStep(
                step_id="left",
                step_type="artifact_step",
                name="Left",
                depends_on=["root"],
                inputs={"path": "outputs/left.md", "content": "left"},
            ),
            WorkflowStep(
                step_id="right",
                step_type="artifact_step",
                name="Right",
                depends_on=["root"],
                inputs={"path": "outputs/right.md", "content": "right"},
            ),
        ],
    )


def _parallel_artifact_definition(workflow_id: str = "wf.parallel") -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        workflow_type="parallel",
        name="Parallel Artifact Flow",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="a",
                step_type="artifact_step",
                name="A",
                inputs={"path": "outputs/a.md", "content": "a"},
            ),
            WorkflowStep(
                step_id="b",
                step_type="artifact_step",
                name="B",
                inputs={"path": "outputs/b.md", "content": "b"},
            ),
            WorkflowStep(
                step_id="join",
                step_type="artifact_step",
                name="Join",
                depends_on=["a", "b"],
                inputs={"path": "outputs/join.md", "content": "join"},
            ),
        ],
    )


def _engine(tmp_path: Path) -> tuple[WorkflowEngine, WorkspaceService]:
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    engine = WorkflowEngine(workspace_service=ws)
    return engine, ws


class _EchoTool:
    tool_id = "utils.echo"
    name = "utils.echo"
    description = "Echo input text."

    async def invoke(self, args, ctx=None):
        _ = ctx
        return {"echo": str((args or {}).get("text") or "")}


def test_workflow_definition_creation(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    definition = _approval_definition()
    saved = engine.define_workflow(definition)

    assert saved.workflow_id == "wf.approval"
    assert len(saved.steps) == 3


def test_workflow_definition_rejects_unknown_dependency(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    bad = WorkflowDefinition(
        workflow_id="wf.bad",
        workflow_type="dag",
        name="Bad",
        owner_user_id="u1",
        steps=[
            WorkflowStep(step_id="s1", step_type="artifact_step", name="A"),
            WorkflowStep(step_id="s2", step_type="artifact_step", name="B", depends_on=["missing"]),
        ],
    )
    with pytest.raises(WorkflowError):
        engine.define_workflow(bad)


def test_graph_workflow_rejects_cycle(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    cyc = WorkflowDefinition(
        workflow_id="wf.graph.cycle",
        workflow_type="graph",
        name="Cycle",
        owner_user_id="u1",
        steps=[
            WorkflowStep(step_id="a", step_type="artifact_step", name="A", depends_on=["b"]),
            WorkflowStep(step_id="b", step_type="artifact_step", name="B", depends_on=["a"]),
        ],
    )
    with pytest.raises(WorkflowError):
        engine.define_workflow(cyc)


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


def test_dag_workflow_runs_with_dependency_order(tmp_path: Path):
    engine, ws = _engine(tmp_path)
    engine.define_workflow(_dag_artifact_definition())

    run = engine.start_workflow(workflow_id="wf.dag", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_COMPLETED
    status_by_id = {step.step_id: step.status for step in run.steps}
    assert status_by_id["root"] == STEP_STATUS_SUCCEEDED
    assert status_by_id["left"] == STEP_STATUS_SUCCEEDED
    assert status_by_id["right"] == STEP_STATUS_SUCCEEDED

    handle = ws.resolve_workspace_handle(user_id="u1", workspace_id="w1")
    assert (Path(handle.root_path) / "outputs" / "root.md").exists()
    assert (Path(handle.root_path) / "outputs" / "left.md").exists()
    assert (Path(handle.root_path) / "outputs" / "right.md").exists()


def test_parallel_workflow_executes_ready_batch_and_completes(tmp_path: Path):
    engine, ws = _engine(tmp_path)
    engine.define_workflow(_parallel_artifact_definition())

    run = engine.start_workflow(workflow_id="wf.parallel", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_COMPLETED
    status_by_id = {step.step_id: step.status for step in run.steps}
    assert status_by_id["a"] == STEP_STATUS_SUCCEEDED
    assert status_by_id["b"] == STEP_STATUS_SUCCEEDED
    assert status_by_id["join"] == STEP_STATUS_SUCCEEDED

    handle = ws.resolve_workspace_handle(user_id="u1", workspace_id="w1")
    assert (Path(handle.root_path) / "outputs" / "a.md").exists()
    assert (Path(handle.root_path) / "outputs" / "b.md").exists()
    assert (Path(handle.root_path) / "outputs" / "join.md").exists()
    assert run.run_metadata.get("scheduler_mode") == "dependency_batch"


def test_append_run_observation_is_bounded(tmp_path: Path):
    engine, _ = _engine(tmp_path)
    engine.define_workflow(_artifact_definition(path="outputs/proof.md"))
    run = engine.start_workflow(workflow_id="wf.artifact", session_id="s1", user_id="u1", workspace_id="w1")

    for i in range(250):
        engine.append_run_observation(
            run.workflow_run_id,
            {"idx": i, "kind": "tool", "observation": f"obs-{i}"},
        )

    latest_run = engine.get_run(run.workflow_run_id)
    observations = latest_run.run_metadata.get("observations", [])
    assert isinstance(observations, list)
    assert len(observations) == 200
    assert observations[0]["idx"] == 50
    assert observations[-1]["idx"] == 249


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


@pytest.mark.asyncio
async def test_workflow_engine_run_tool_action_executes_tool_and_records_observation(tmp_path: Path):
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    tool_service = ToolService(event_emitter=None)
    tool_service.register_tool(_EchoTool())
    engine = WorkflowEngine(workspace_service=ws, tool_service=tool_service)
    engine.define_workflow(_artifact_definition(workflow_id="wf.tools", path="outputs/x.md"))
    run = engine.start_workflow(workflow_id="wf.tools", session_id="s1", user_id="u1", workspace_id="w1")

    out = await engine.run_tool_action(
        workflow_run_id=run.workflow_run_id,
        session_id="s1",
        user_id="u1",
        tool_type="local",
        service_name="utils",
        tool_name="utils.echo",
        args={"text": "ok"},
        run_context=None,
        user_config={"tools": {"allow": ["*"]}},
    )
    assert out["workflow_managed"] is True
    assert out["result"]["echo"] == "ok"
    latest = engine.get_run(run.workflow_run_id)
    observations = latest.run_metadata.get("observations", [])
    assert isinstance(observations, list)
    assert len(observations) >= 1


def test_tool_step_executes_real_tool_in_workflow(tmp_path: Path):
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    tool_service = ToolService(event_emitter=None)
    tool_service.register_tool(_EchoTool())
    engine = WorkflowEngine(workspace_service=ws, tool_service=tool_service)
    definition = WorkflowDefinition(
        workflow_id="wf.tool_step",
        name="Tool Step",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="s1",
                step_type="tool_step",
                name="Echo",
                inputs={"tool_name": "utils.echo", "args": {"text": "from-step"}},
            )
        ],
    )
    engine.define_workflow(definition)
    run = engine.start_workflow(workflow_id="wf.tool_step", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_COMPLETED
    assert run.steps[0].status == STEP_STATUS_SUCCEEDED
    assert run.steps[0].outputs.get("result", {}).get("echo") == "from-step"


def test_tool_step_without_tool_service_reports_structured_dependency_failure(tmp_path: Path):
    ws = WorkspaceService(base_dir=str(tmp_path / "ws"))
    engine = WorkflowEngine(workspace_service=ws, tool_service=None)
    definition = WorkflowDefinition(
        workflow_id="wf.no_tools",
        name="No Tool Service",
        owner_user_id="u1",
        steps=[
            WorkflowStep(
                step_id="s1",
                step_type="tool_step",
                name="Echo",
                inputs={"tool_name": "utils.echo", "args": {"text": "x"}},
            )
        ],
    )
    engine.define_workflow(definition)
    run = engine.start_workflow(workflow_id="wf.no_tools", session_id="s1", user_id="u1", workspace_id="w1")
    assert run.status == RUN_STATUS_FAILED
    assert run.steps[0].status == STEP_STATUS_FAILED
    assert run.steps[0].outputs.get("error_code") == "dependency_unavailable"
    assert run.steps[0].outputs.get("dependency") == "tool_service"
