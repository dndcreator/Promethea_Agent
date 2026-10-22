"""Durable action checkpoints, independent from the Task persistence backend."""
from copy import deepcopy

from .models import ActionRun
from .state_machine import RuntimeActionStateMachine


def capture(run, messages, usage, *, pending_calls=None, result=None):
    return {
        "version": 1, "action_loop_id": run.run_id, "goal": run.goal, "budget": run.budget,
        "step": run.step, "messages": deepcopy(messages), "usage": dict(usage),
        "transitions": deepcopy(run.machine.transitions), "trace": deepcopy(run.trace),
        "observations": deepcopy(run.observations), "execution_path": deepcopy(run.execution_path),
        "reasoning_steps": deepcopy(run.reasoning_steps), "pending_calls": deepcopy(pending_calls or []),
        "result": deepcopy(result),
    }


def restore(value, context):
    if value.get("version") != 1:
        raise ValueError("unsupported action checkpoint version")
    return ActionRun(
        goal=str(value["goal"]), messages=deepcopy(value["messages"]), context=context,
        run_id=str(value["action_loop_id"]), budget=int(value["budget"] or 5),
        step=int(value["step"]), machine=RuntimeActionStateMachine.restore(value["transitions"]),
        trace=deepcopy(value["trace"]), observations=deepcopy(value["observations"]),
        execution_path=deepcopy(value["execution_path"]), reasoning_steps=deepcopy(value["reasoning_steps"]),
    )
