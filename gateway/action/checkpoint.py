"""Durable action checkpoints, independent from the Task persistence backend."""
from copy import deepcopy

from .models import ActionRun
from .state_machine import RuntimeActionStateMachine, ActionPhase
from gateway.goal_gaps import GoalGapState


def capture(run, messages, usage, *, pending_calls=None, result=None):
    return {
        "version": 1, "action_loop_id": run.run_id, "goal": run.goal, "budget": run.budget,
        "step": run.step, "messages": deepcopy(messages), "usage": dict(usage),
        "progress_grace_steps": run.progress_grace_steps,
        "transitions": deepcopy(run.machine.transitions), "trace": deepcopy(run.trace),
        "observations": deepcopy(run.observations), "execution_path": deepcopy(run.execution_path),
        "reasoning_steps": deepcopy(run.reasoning_steps), "pending_calls": deepcopy(pending_calls or []),
        "result": deepcopy(result),
        "applied_steering_ids": list(run.applied_steering_ids),
        "model_recovery": deepcopy(run.model_recovery),
        "model_protocol": run.model_protocol, "model_wire": deepcopy(run.model_wire),
        "pending_input": deepcopy(run.pending_input),
        "goal_gaps": run.gap_state.model_dump(), "gap_feedback": run.gap_feedback,
        "runtime_scope": {"user_id": run.context.user_id, "session_id": run.context.session_id,
                          **{key: getattr(run.context.run_context, key, None) for key in ("task_id", "task_run_id")}},
    }


def restore(value, context):
    if value.get("version") != 1:
        raise ValueError("unsupported action checkpoint version")
    scope = value.get("runtime_scope") or {}
    actual = {"user_id": context.user_id, "session_id": context.session_id,
              **{key: getattr(context.run_context, key, None) for key in ("task_id", "task_run_id")}}
    if any(scope.get(key) != actual.get(key) for key in scope):
        raise PermissionError("action checkpoint does not belong to this Runtime scope")
    return ActionRun(
        goal=str(value["goal"]), messages=deepcopy(value["messages"]), context=context,
        run_id=str(value["action_loop_id"]), budget=int(value["budget"] or 5),
        progress_grace_steps=int(value.get("progress_grace_steps") or 0),
        step=int(value["step"]), machine=RuntimeActionStateMachine.restore(value["transitions"]),
        trace=deepcopy(value["trace"]), observations=deepcopy(value["observations"]),
        execution_path=deepcopy(value["execution_path"]), reasoning_steps=deepcopy(value["reasoning_steps"]),
        applied_steering_ids=list(value.get("applied_steering_ids") or []),
        model_recovery=deepcopy(value.get("model_recovery") or {}),
        model_protocol=value.get("model_protocol", "prompt_json"), model_wire=deepcopy(value.get("model_wire") or {}),
        pending_input=deepcopy(value.get("pending_input")),
        gap_state=GoalGapState.model_validate(value.get("goal_gaps") or {}), gap_feedback=str(value.get("gap_feedback") or ""),
    )


def continue_run(value, context, *, goal, budget=None):
    previous = restore(value, context)
    outcome = (value.get("result") or {}).get("execution_outcome") or {}
    if previous.machine.phase != ActionPhase.COMPLETED or outcome.get("stop_reason") not in {"budget_exhausted", "recovery_exhausted"}:
        raise ValueError("only a settled budget-stopped checkpoint can begin another slice")
    if previous.goal != goal:
        raise ValueError("continuation goal differs from the saved checkpoint")
    run = ActionRun(
        goal=goal, messages=previous.messages, context=context, budget=budget or previous.budget,
        observations=previous.observations, execution_path=previous.execution_path,
        reasoning_steps=previous.reasoning_steps,
        model_protocol=previous.model_protocol, model_wire=previous.model_wire,
        gap_state=previous.gap_state.model_copy(deep=True), gap_feedback=previous.gap_feedback,
    )
    context.metadata["continuation_of"] = previous.run_id
    run.gap_state.recovery.rejections = run.gap_state.recovery.failed_trials = 0
    run.add_trace("action.continued", {"continuation_of": previous.run_id})
    return run
