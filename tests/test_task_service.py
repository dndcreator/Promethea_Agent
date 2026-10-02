import asyncio
from pathlib import Path

import pytest

from gateway.task_service import TaskExecutionConflict, TaskRevisionConflict, TaskService
from gateway.task_runtime import TaskRuntime
from gateway.workflow_engine import WorkflowEngine
from gateway.workflow_models import WorkflowDefinition, WorkflowStep


def test_task_service_persists_runs_and_events(tmp_path: Path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task = service.create_task(user_id="u1", title="Research", session_id="s1")
    service.start_run(task_id=task["task_id"], user_id="u1", run_id="run_1", run_type="action", session_id="s1")
    service.update_run(task_id=task["task_id"], user_id="u1", run_id="run_1", status="completed")
    restored = TaskService(storage_path=str(tmp_path / "tasks.json")).get_task(task["task_id"], user_id="u1")
    assert restored["status"] == "completed"
    event_types = [event["event_type"] for event in restored["events"]]
    assert event_types.count("task.state.changed") == 2
    assert {"task.created", "task.run.started", "task.run.updated"}.issubset(event_types)


def test_task_service_fails_loud_on_corrupt_state(tmp_path: Path):
    path = tmp_path / "tasks.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed to load durable task state"):
        TaskService(storage_path=str(path))


def test_workflow_run_becomes_task_run(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    engine = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks)
    engine.define_workflow(WorkflowDefinition(workflow_id="wf.one", name="One", owner_user_id="u1", steps=[WorkflowStep(step_id="s1", step_type="summary_step", name="Done")]))
    run = engine.start_workflow(workflow_id="wf.one", session_id="s1", user_id="u1")
    task = tasks.get_task(run.run_metadata["task_id"], user_id="u1")
    assert task["runs"][0]["run_id"] == run.workflow_run_id
    assert task["runs"][0]["status"] == "completed"


def test_ephemeral_workflow_does_not_create_task(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    engine = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks)
    engine.define_workflow(WorkflowDefinition(workflow_id="wf.trace", name="Trace", owner_user_id="u1", steps=[WorkflowStep(step_id="s1", step_type="summary_step", name="Done")]))

    run = engine.start_workflow(
        workflow_id="wf.trace",
        session_id="s1",
        user_id="u1",
        run_metadata={"task_mode": "ephemeral"},
    )

    assert "task_id" not in run.run_metadata
    assert tasks.list_tasks(user_id="u1") == []


def test_task_state_machine_controls_explicit_lifecycle(tmp_path: Path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task = service.create_task(user_id="u1", title="Long task")
    task_id = task["task_id"]

    paused = service.transition_task(task_id=task_id, user_id="u1", status="paused")
    assert paused["status"] == "paused"
    resumed = service.transition_task(task_id=task_id, user_id="u1", status="running")
    assert resumed["status"] == "running"
    cancelled = service.transition_task(task_id=task_id, user_id="u1", status="cancelled")
    assert cancelled["status"] == "cancelled"


def test_task_revision_rejects_stale_commands(tmp_path: Path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task = service.create_task(user_id="u1", title="Versioned")

    updated = service.update_task(
        task_id=task["task_id"], user_id="u1", objective="new", expected_revision=task["revision"],
    )

    assert updated["revision"] > task["revision"]
    with pytest.raises(TaskRevisionConflict):
        service.update_task(
            task_id=task["task_id"], user_id="u1", objective="stale", expected_revision=task["revision"],
        )


def test_task_execution_attempts_are_epoch_fenced(tmp_path: Path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task = service.create_task(user_id="u1", title="Fenced")
    service.start_run(task_id=task["task_id"], user_id="u1", run_id="run_1", run_type="workflow")

    first = service.claim_execution(task_id=task["task_id"], user_id="u1", run_id="run_1", owner_id="runtime_1")
    with pytest.raises(TaskExecutionConflict):
        service.claim_execution(task_id=task["task_id"], user_id="u1", run_id="run_1", owner_id="runtime_2")
    service.settle_execution(task_id=task["task_id"], user_id="u1", token=first, status="interrupted")
    second = service.claim_execution(task_id=task["task_id"], user_id="u1", run_id="run_1", owner_id="runtime_2")

    assert second["epoch"] == first["epoch"] + 1
    with pytest.raises(TaskExecutionConflict):
        service.assert_execution(task_id=task["task_id"], user_id="u1", token=first)


def test_task_execution_leases_are_scoped_per_run(tmp_path: Path):
    service = TaskService(storage_path=str(tmp_path / "tasks.json"))
    task = service.create_task(user_id="u1", title="Parallel")
    service.start_run(task_id=task["task_id"], user_id="u1", run_id="run_1", run_type="workflow")
    service.start_run(task_id=task["task_id"], user_id="u1", run_id="run_2", run_type="workflow")

    first = service.claim_execution(task_id=task["task_id"], user_id="u1", run_id="run_1", owner_id="runtime_1")
    second = service.claim_execution(task_id=task["task_id"], user_id="u1", run_id="run_2", owner_id="runtime_2")

    assert first["run_id"] != second["run_id"]
    assert len(service.get_task(task["task_id"], user_id="u1")["executions"]) == 2


async def test_detached_task_run_continues_after_start_returns(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    engine = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks)
    engine.define_workflow(
        WorkflowDefinition(
            workflow_id="wf.detached",
            name="Detached",
            owner_user_id="u1",
            steps=[WorkflowStep(step_id="s1", step_type="summary_step", name="Done")],
        )
    )
    task = tasks.create_task(user_id="u1", title="Detached", session_id="s1")
    runtime = TaskRuntime(task_service=tasks, workflow_engine=engine)

    run = runtime.start_workflow(
        task_id=task["task_id"],
        user_id="u1",
        workflow_id="wf.detached",
        session_id="s1",
    )

    assert run["status"] == "running"
    assert run["workflow_run_id"] in runtime.active_run_ids()
    await asyncio.sleep(0.05)
    persisted = tasks.get_task(task["task_id"], user_id="u1")
    assert persisted["status"] == "completed"
    assert persisted["executions"] == {}
    assert persisted["runs"][0]["attempts"][0]["status"] == "completed"
    assert run["workflow_run_id"] not in runtime.active_run_ids()


async def test_task_runtime_recovers_running_run_after_restart(tmp_path: Path):
    task_path = tmp_path / "tasks.json"
    workflow_path = tmp_path / "workflow.json"
    tasks = TaskService(storage_path=str(task_path))
    engine = WorkflowEngine(storage_path=str(workflow_path), task_service=tasks)
    engine.define_workflow(
        WorkflowDefinition(
            workflow_id="wf.recover",
            name="Recover",
            owner_user_id="u1",
            steps=[WorkflowStep(step_id="s1", step_type="summary_step", name="Done")],
        )
    )
    task = tasks.create_task(user_id="u1", title="Recover", session_id="s1")
    run = engine.prepare_workflow_run(
        workflow_id="wf.recover",
        session_id="s1",
        user_id="u1",
        run_metadata={"task_id": task["task_id"], "execution_owner": "task_runtime"},
    )
    run.steps[0].status = "running"
    run.steps[0].attempt_count = 1
    run.steps[0].active_attempt_id = "step_attempt_old"
    run.steps[0].idempotency_key = f"{run.workflow_run_id}:s1:1"
    engine._persist_state()

    restored_tasks = TaskService(storage_path=str(task_path))
    restored_engine = WorkflowEngine(storage_path=str(workflow_path), task_service=restored_tasks)
    runtime = TaskRuntime(task_service=restored_tasks, workflow_engine=restored_engine)
    assert await runtime.recover_incomplete() == 1
    await asyncio.sleep(0.05)

    restored = restored_tasks.get_task(task["task_id"], user_id="u1")
    assert restored["status"] == "completed"
    assert restored_engine.get_run(run.workflow_run_id).status == "completed"
    repaired_step = restored_engine.get_run(run.workflow_run_id).steps[0]
    assert repaired_step.attempt_count == 2
    assert repaired_step.attempt_history[0]["status"] == "interrupted"


async def test_paused_task_run_can_resume_in_detached_runtime(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    engine = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks)
    engine.define_workflow(
        WorkflowDefinition(
            workflow_id="wf.pause",
            name="Pause",
            owner_user_id="u1",
            steps=[WorkflowStep(step_id="s1", step_type="summary_step", name="Done")],
        )
    )
    task = tasks.create_task(user_id="u1", title="Pause", session_id="s1")
    run = engine.prepare_workflow_run(
        workflow_id="wf.pause",
        session_id="s1",
        user_id="u1",
        run_metadata={"task_id": task["task_id"], "execution_owner": "task_runtime"},
    )
    engine.pause_workflow(run.workflow_run_id)
    runtime = TaskRuntime(task_service=tasks, workflow_engine=engine)

    resumed = runtime.resume_task(task_id=task["task_id"], user_id="u1")
    assert resumed["status"] == "paused"
    await asyncio.sleep(0.05)

    assert tasks.get_task(task["task_id"], user_id="u1")["status"] == "completed"


async def test_task_runtime_reclaims_due_retry_as_new_attempt(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    engine = WorkflowEngine(storage_path=str(tmp_path / "workflow.json"), task_service=tasks, capability_service=object())
    calls = 0

    async def flaky(run, step, *, run_context=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("offline")
        return {"result": "online"}

    engine._execute_tool_step_async = flaky
    engine.define_workflow(WorkflowDefinition(
        workflow_id="wf.retry-runtime",
        name="Retry runtime",
        owner_user_id="u1",
        steps=[WorkflowStep(
            step_id="s1", step_type="tool_step", name="Call",
            retry_policy={"max_attempts": 2, "backoff_seconds": 0.1},
        )],
    ))
    task = tasks.create_task(user_id="u1", title="Retry runtime")
    runtime = TaskRuntime(task_service=tasks, workflow_engine=engine)

    run = runtime.start_workflow(
        task_id=task["task_id"], user_id="u1", workflow_id="wf.retry-runtime", session_id="s1",
    )
    await asyncio.sleep(0.2)
    assert engine.get_run(run["workflow_run_id"]).status == "retry_wait"

    assert await runtime._recover_available() == 1
    await asyncio.sleep(0.2)
    restored = tasks.get_task(task["task_id"], user_id="u1")
    assert restored["status"] == "completed"
    assert [row["status"] for row in restored["runs"][0]["attempts"]] == ["retry_wait", "completed"]
