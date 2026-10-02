from gateway.workflow_engine import WorkflowEngine
from gateway.workflow_models import RUN_STATUS_RUNNING, RUN_STATUS_PAUSED, WorkflowDefinition, WorkflowRun, WorkflowStep


def test_imported_running_workflow_is_paused(tmp_path):
    engine = WorkflowEngine(storage_path=tmp_path / "workflow.json")
    definition = WorkflowDefinition(
        workflow_id="wf1", owner_user_id="u1", name="Test", steps=[WorkflowStep(step_id="s1", step_type="reasoning_step", name="Step")]
    )
    run = WorkflowRun(workflow_run_id="run1", workflow_id="wf1", session_id="s1", user_id="u1", workspace_id="w1", status=RUN_STATUS_RUNNING)
    payload = {"definitions": {"wf1": definition.model_dump(mode="json")}, "runs": {"run1": run.model_dump(mode="json")}, "checkpoints": {}}

    result = engine.import_user_state(user_id="u1", payload=payload, merge=True)

    assert result["runs"] == 1
    assert engine.get_run("run1").status == RUN_STATUS_PAUSED
