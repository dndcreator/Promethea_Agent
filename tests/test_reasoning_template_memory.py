from pathlib import Path

from gateway.reasoning_template_memory import ReasoningTemplateMemory


def _sample_tree_payload():
    return {
        "tree_id": "t1",
        "session_id": "s1",
        "user_id": "u1",
        "root_goal": "build release checklist",
        "status": "completed",
        "stats": {
            "iterations": 3,
            "memory_calls": 1,
            "tool_calls": 1,
            "think_calls": 2,
        },
        "nodes": [
            {
                "kind": "thought",
                "title": "break down checklist",
                "metadata": {
                    "title": "break down checklist",
                    "goal": "split release process into phases",
                    "requires_memory": False,
                    "requires_tools": False,
                },
            },
            {
                "kind": "tool",
                "title": "tool: docs.search",
                "metadata": {
                    "service_name": "docs",
                    "tool_name": "search",
                },
            },
        ],
    }


def test_reasoning_template_memory_record_and_match(tmp_path: Path):
    store = ReasoningTemplateMemory(base_dir=tmp_path / "reasoning_templates")

    store.record_success(
        user_id="u1",
        session_id="s1",
        user_message="Build a release checklist for deployment",
        assistant_output="Here is the release checklist...",
        gate={"needs_reasoning": True, "needs_tools": True, "needs_memory": False},
        policy={"plan_max_steps": 5, "branch_factor": 3, "beam_width": 3},
        tree_payload=_sample_tree_payload(),
    )

    matched = store.match_template(
        user_id="u1",
        task="Can you create a deployment release checklist?",
    )
    assert matched["matched"] is True
    assert matched["score"] > 0.0
    assert matched["template"]

    assert (tmp_path / "reasoning_templates" / "u1.templates.json").exists()
    assert (tmp_path / "reasoning_templates" / "u1.paths.jsonl").exists()
    assert (tmp_path / "reasoning_templates" / "u1.opro.json").exists()


def test_reasoning_template_memory_hints_include_preferred_tools(tmp_path: Path):
    store = ReasoningTemplateMemory(base_dir=tmp_path / "reasoning_templates")
    tree = _sample_tree_payload()

    store.record_success(
        user_id="u1",
        session_id="s1",
        user_message="Write deployment checklist",
        assistant_output="ok",
        gate={"needs_reasoning": True},
        policy={},
        tree_payload=tree,
    )
    store.record_success(
        user_id="u1",
        session_id="s2",
        user_message="Plan deployment checklist",
        assistant_output="ok",
        gate={"needs_reasoning": True},
        policy={},
        tree_payload=tree,
    )

    hints = store.get_strategy_hints(user_id="u1")
    assert hints["template_count"] >= 1
    assert hints["max_steps_hint"] >= 1
    assert hints["branch_factor_hint"] >= 1
    assert isinstance(hints["preferred_tools"], list)
