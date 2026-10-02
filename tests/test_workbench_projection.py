import asyncio
from pathlib import Path

from gateway.runtime_event_log import RuntimeEventLog
from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.task_service import TaskService
from gateway.workbench_projection import WorkbenchProjection
from gateway.workflow_engine import WorkflowEngine


def test_workbench_projects_task_scoped_runtime_timeline(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Morning research", session_id="s1")
    task_id = task["task_id"]
    event_log.append(
        event_type="tool.execution.started",
        payload={
            "user_id": "u1",
            "session_id": "s1",
            "task_id": task_id,
            "run_id": "run_1",
            "tool_name": "web.search",
        },
        durable=False,
    )
    projection = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    )

    snapshot = projection.snapshot(user_id="u1", session_id="s1")

    assert snapshot["task"]["task_id"] == task_id
    assert snapshot["timeline"][0]["kind"] == "tool"
    assert snapshot["timeline"][0]["subject"] == "web.search"
    assert snapshot["scope"]["task_id"] == task_id
    assert snapshot["cursor"] > 0


def test_workbench_session_scope_does_not_fall_back_to_another_task(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    tasks.create_task(user_id="u1", title="Other task", session_id="other-session")

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", session_id="new-session")

    assert snapshot["task"] is None
    assert snapshot["scope"]["task_id"] is None
    assert snapshot["scope"]["session_id"] == "new-session"


async def test_workbench_projection_follows_runtime_events_incrementally(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter(event_log)
    task = tasks.create_task(user_id="u1", title="Live", session_id="s1")
    projection = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
        event_emitter=emitter,
    )

    projection.snapshot(user_id="u1", session_id="s1")
    await emitter.emit(
        EventType.MEMORY_RECALL_STARTED,
        {"user_id": "u1", "session_id": "s1", "task_id": task["task_id"], "request_id": "r1"},
    )
    snapshot = projection.snapshot(user_id="u1", task_id=task["task_id"])

    assert snapshot["timeline"][-1]["kind"] == "memory"
    assert snapshot["timeline"][-1]["event_type"] == "memory.recall.started"


async def test_workbench_projection_wakes_matching_stream_subscriber(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter(event_log)
    task = tasks.create_task(user_id="u1", title="Watch", session_id="s1")
    projection = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
        event_emitter=emitter,
    )
    cursor = projection.snapshot(user_id="u1", task_id=task["task_id"])["cursor"]
    waiter = asyncio.create_task(projection.wait_for_change(
        user_id="u1",
        task_id=task["task_id"],
        after_seq=cursor,
        timeout=1.0,
    ))
    await asyncio.sleep(0)

    await emitter.emit(
        EventType.TOOL_CALL_START,
        {"user_id": "u1", "session_id": "s1", "task_id": task["task_id"], "tool_name": "demo"},
    )

    assert await waiter is True


def test_workbench_coalesces_tool_lifecycle_and_compatibility_events(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Research", session_id="s1")
    common = {
        "user_id": "u1",
        "session_id": "s1",
        "task_id": task["task_id"],
        "tool_call_id": "call_1",
        "tool_name": "web.search",
    }
    for event_type, payload in (
        ("tool.call.start", {**common, "status": "running"}),
        ("tool.execution.started", {**common, "status": "running"}),
        (
            "tool.call.result",
            {
                **common,
                "status": "completed",
                "result_summary": "Found 8 sources",
                "result_metadata": {
                    "kind": "web_search",
                    "provider": "brave",
                    "sources": [{"title": "Promethea", "url": "https://example.com"}],
                },
            },
        ),
        ("tool.execution.finished", {**common, "status": "completed", "result_summary": "Found 8 sources"}),
    ):
        event_log.append(event_type=event_type, payload=payload, durable=False)

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", task_id=task["task_id"])

    assert len(snapshot["timeline"]) == 1
    assert snapshot["timeline"][0]["activity_id"] == "tool:call_1"
    assert snapshot["timeline"][0]["status"] == "completed"
    assert snapshot["timeline"][0]["summary"] == "Found 8 sources"
    assert snapshot["timeline"][0]["detail"]["result_metadata"]["provider"] == "brave"


def test_workbench_hides_transport_and_execution_bookkeeping(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Quiet projection", session_id="s1")
    common = {"user_id": "u1", "session_id": "s1", "task_id": task["task_id"]}
    for event_type in ("request.received", "conversation.stage.started", "task.execution.claimed"):
        event_log.append(event_type=event_type, payload=common, durable=False)

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", task_id=task["task_id"])

    assert snapshot["timeline"] == []


def test_workbench_keeps_reasoning_as_readable_state_not_raw_nodes(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Plan", session_id="s1")
    common = {
        "user_id": "u1",
        "session_id": "s1",
        "task_id": task["task_id"],
        "node_id": "node_1",
        "kind": "reasoning",
        "title": "Compare available approaches",
    }
    event_log.append(event_type="reasoning.node.created", payload={**common, "status": "running"}, durable=False)
    event_log.append(
        event_type="reasoning.node.completed",
        payload={**common, "status": "succeeded", "observation": "Selected the lower-risk approach"},
        durable=False,
    )

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", task_id=task["task_id"])

    assert len(snapshot["timeline"]) == 1
    assert snapshot["timeline"][0]["kind"] == "reasoning"
    assert snapshot["timeline"][0]["subject"] == "Compare available approaches"
    assert snapshot["timeline"][0]["summary"] == "Selected the lower-risk approach"


def test_workbench_correlates_memory_completion_without_repeating_query(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Recall", session_id="s1")
    common = {
        "user_id": "u1",
        "session_id": "s1",
        "task_id": task["task_id"],
        "request_id": "memory_request_1",
    }
    event_log.append(
        event_type="memory.recall.started",
        payload={**common, "query": "preferred writing style"},
        durable=False,
    )
    event_log.append(
        event_type="memory.recall.finished",
        payload={**common, "status": "completed", "selected": 3},
        durable=False,
    )

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", task_id=task["task_id"])

    assert len(snapshot["timeline"]) == 1
    assert snapshot["timeline"][0]["activity_id"] == "memory:memory_request_1"
    assert snapshot["timeline"][0]["subject"] == "preferred writing style"
    assert snapshot["timeline"][0]["status"] == "completed"


def test_workbench_projects_interrupted_environment_as_recovery_action(tmp_path: Path):
    tasks = TaskService(storage_path=str(tmp_path / "tasks.json"))
    workflows = WorkflowEngine(storage_path=str(tmp_path / "workflows.json"), task_service=tasks)
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    task = tasks.create_task(user_id="u1", title="Draft", session_id="s1")
    event_log.append(
        event_type="environment.state.changed",
        payload={
            "kind": "environment",
            "user_id": "u1",
            "session_id": "s1",
            "task_id": task["task_id"],
            "environment_id": "env_1",
            "name": "Document editor",
            "status": "interrupted",
            "action": "interrupted",
            "revision": 2,
        },
        durable=False,
    )

    snapshot = WorkbenchProjection(
        task_service=tasks,
        workflow_engine=workflows,
        event_log=event_log,
    ).snapshot(user_id="u1", task_id=task["task_id"])

    assert snapshot["timeline"][0]["kind"] == "environment"
    assert snapshot["timeline"][0]["subject"] == "Document editor"
    assert snapshot["waiting_actions"][0] == {
        "kind": "environment_recovery",
        "id": "env_1",
        "task_id": task["task_id"],
        "status": "interrupted",
    }
