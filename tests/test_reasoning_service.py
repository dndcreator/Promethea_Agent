import pytest

from gateway.reasoning_service import ReasoningService


class DummyConversationCore:
    async def call_llm(self, messages, user_config=None, user_id=None):
        return {"content": "{}"}


@pytest.mark.asyncio
async def test_run_skips_reasoning_for_simple_non_action_task(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore())

    async def fake_gate(**kwargs):
        return {
            "needs_reasoning": False,
            "needs_memory": False,
            "needs_tools": False,
            "complexity": "low",
            "reason": "test",
        }

    monkeypatch.setattr(svc, "_gate_reasoning", fake_gate)

    result = await svc.run(
        session_id="s1",
        user_id="u1",
        user_message="hello",
        recent_messages=[],
        base_system_prompt="You are helpful.",
        user_config={"reasoning": {"enabled": True}},
    )

    assert result["used_reasoning"] is False
    assert result["gate"]["needs_reasoning"] is False


@pytest.mark.asyncio
async def test_plan_steps_normalizes_string_booleans(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore())
    tree = svc._create_tree(session_id="s1", user_id="u1", root_goal="task")

    async def fake_call_json(messages, user_config=None, user_id=None):
        return {
            "steps": [
                {
                    "title": "step-1",
                    "goal": "do something",
                    "requires_memory": "false",
                    "memory_query": "",
                    "requires_tools": "true",
                    "tool_intent": "search",
                    "notes": "",
                }
            ]
        }

    monkeypatch.setattr(svc, "_call_json", fake_call_json)

    steps = await svc._plan_steps(
        tree=tree,
        user_message="task",
        recent_messages=[],
        user_config={"reasoning": {"enabled": True}},
        user_id="u1",
        policy={
            "plan_max_steps": 3,
            "max_replan_rounds": 2,
            "max_depth": 3,
            "max_nodes": 20,
            "max_iterations": 5,
            "max_memory_calls": 2,
            "max_tool_calls": 2,
            "beam_width": 2,
            "branch_factor": 2,
            "candidate_votes": 2,
            "min_branch_score": 0.0,
        },
    )

    assert len(steps) == 1
    assert steps[0]["requires_memory"] is False
    assert steps[0]["requires_tools"] is True

