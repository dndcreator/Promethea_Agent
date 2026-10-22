import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from gateway.reasoning_evaluation import collect_observation_samples, judge_runtime_feasibility, judge_task_success
from gateway.reasoning_models import ReasoningNode, ReasoningTree


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, {"outcome": "unexpected", "confidence": "invalid"}])
async def test_task_evaluation_normalizes_uncertain_output(result):
    call = AsyncMock(return_value=result)
    out = await judge_task_success(call, user_message="Task", assistant_output="Answer", gate={}, policy={},
                                   tree_stats={}, user_config=None, user_id="u")
    assert out["outcome"] == "unsure" and out["confidence"] == 0.0
    assert call.await_args.kwargs == {"user_config": None, "user_id": "u"}


def test_observation_sampling_is_bounded_and_does_not_mutate_tree():
    tree = ReasoningTree(tree_id="t", session_id="s", user_id="u", root_goal="Task")
    for index, text in enumerate(["[tool error] " + "x" * 800, "Done " + "y" * 800, "Done again"]):
        tree.nodes[str(index)] = ReasoningNode(node_id=str(index), parent_id=None, kind="tool", title="Step", observation=text)
    previous = deepcopy(tree)
    samples = collect_observation_samples(tree=tree, limit=1)
    assert len(samples["failed"]) == len(samples["succeeded"]) == 1
    assert all(len(item) <= 500 for rows in samples.values() for item in rows)
    assert tree == previous


@pytest.mark.asyncio
async def test_model_evaluation_cannot_finish_or_change_runtime_tree():
    tree = ReasoningTree(tree_id="t", session_id="s", user_id="u", root_goal="Task")
    previous = deepcopy(tree)
    call = AsyncMock(return_value={"outcome": "success", "confidence": 4.0, "suggestion": "done"})
    out = await judge_runtime_feasibility(call, user_message="Task", tree=tree, policy={}, iteration_budget=3,
                                          user_config=None, user_id="u")
    assert out == {"outcome": "success", "confidence": 1.0, "reason": "", "suggestion": "done"}
    assert tree == previous and tree.status == "running"
    payload = json.loads(call.await_args.args[0][1]["content"])
    assert payload["iteration_budget"] == 3 and payload["tree_stats"] == tree.stats
