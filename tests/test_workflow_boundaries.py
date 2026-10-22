import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.workflow_definition import dependencies_satisfied, normalize_definition, select_next_ready_step_id, validate_definition
from gateway.workflow_engine import WorkflowEngine, WorkflowError
from gateway.workflow_models import Checkpoint, WorkflowDefinition, WorkflowError as DomainError, WorkflowRun, WorkflowStep
from gateway import workflow_state_store as storage


def definition(workflow_type="linear", steps=None):
    return WorkflowDefinition(workflow_id="wf", name="Test", workflow_type=workflow_type, steps=steps or [
        WorkflowStep(step_id="a", step_type="reasoning_step", name="First"),
        WorkflowStep(step_id="b", step_type="reasoning_step", name="Second"),
    ])


def test_definition_and_dependency_selection_do_not_advance_state():
    model = definition()
    normalize_definition(model)
    validate_definition(model)
    assert model.steps[1].depends_on == ["a"]
    before = model.model_dump()
    assert select_next_ready_step_id(model.steps) == "a"
    assert model.model_dump() == before
    assert not dependencies_satisfied(model.steps[1], model.steps)
    model.steps[0].status = "skipped"
    assert select_next_ready_step_id(model.steps) == "b"
    assert model.steps[1].status == "pending"
    assert WorkflowError is DomainError


def test_cycle_validation_preserves_domain_error():
    model = definition("dag")
    model.steps[0].depends_on = ["b"]
    model.steps[1].depends_on = ["a"]
    with pytest.raises(WorkflowError, match="dependency cycle"):
        validate_definition(model)


def test_store_round_trip_keeps_runs_checkpoints_and_input_unchanged(tmp_path):
    path = tmp_path / "workflow.json"
    model = definition()
    run = WorkflowRun(workflow_run_id="r", workflow_id="wf", session_id="s", user_id="u", workspace_id="w", steps=model.steps)
    checkpoint = Checkpoint(checkpoint_id="c", workflow_run_id="r", step_id="a", run_context_snapshot={"when": datetime(2026, 1, 1, tzinfo=timezone.utc), "path": Path("artifact.md")})
    storage.save_workflow_state(path, definitions={"wf": model}, runs={"r": run}, checkpoints={"r": [checkpoint]})
    definitions, runs, checkpoints = storage.load_workflow_state(path)
    assert definitions["wf"] == model and runs["r"] == run
    assert checkpoints["r"][0].run_context_snapshot == {"when": "2026-01-01T00:00:00Z", "path": "artifact.md"}
    assert isinstance(checkpoint.run_context_snapshot["when"], datetime)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_keeps_previous_durable_file_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / "workflow.json"
    storage.save_workflow_state(path, definitions={}, runs={}, checkpoints={})
    previous = path.read_bytes()

    def fail(*_args):
        raise PermissionError("locked")

    monkeypatch.setattr(storage, "_replace_state_file", fail)
    with pytest.raises(PermissionError):
        storage.save_workflow_state(path, definitions={"wf": definition()}, runs={}, checkpoints={})
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def test_invalid_load_does_not_partially_replace_engine_state(tmp_path):
    path = tmp_path / "workflow.json"
    engine = WorkflowEngine(storage_path=str(path))
    original = engine.define_workflow(definition())
    path.write_text(json.dumps({"definitions": {"other": definition().model_dump(mode="json")}, "runs": {"bad": {}}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid workflow run"):
        engine._load_state()
    assert engine.get_workflow("wf") is original
    assert engine.get_workflow("other") is None


def test_snapshot_serialization_does_not_retain_mutable_runtime_references():
    context = SimpleNamespace(items=[{"value": 1}])
    snapshot = storage.snapshot_dict(context)
    context.items[0]["value"] = 2
    assert snapshot == {"items": [{"value": 1}]}
