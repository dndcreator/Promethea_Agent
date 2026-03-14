import pytest

from gateway.reasoning_service import ReasoningService


class DummyConversationCore:
    async def call_llm(self, messages, user_config=None, user_id=None):
        return {"content": "{}"}


class DummyTemplateMemory:
    def __init__(self):
        self.saved = []

    def record_success(self, **kwargs):
        self.saved.append(kwargs)

    def match_template(self, *, user_id, task):
        return {"matched": False, "score": 0.0, "template": None}

    def get_strategy_hints(self, *, user_id):
        return {}


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


@pytest.mark.asyncio
async def test_gate_reasoning_normalizes_string_booleans(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore())

    monkeypatch.setattr(
        svc,
        "_heuristic_gate",
        lambda user_message: {
            "needs_reasoning": True,
            "complexity": "high",
            "needs_memory": True,
            "needs_tools": True,
            "reason": "heuristic",
        },
    )

    async def fake_call_json(messages, user_config=None, user_id=None):
        return {
            "needs_reasoning": "false",
            "needs_memory": "0",
            "needs_tools": "no",
            "reason": "llm",
        }

    monkeypatch.setattr(svc, "_call_json", fake_call_json)

    gate = await svc._gate_reasoning(
        user_message="any task",
        recent_messages=[],
        user_config={"reasoning": {"enabled": True}},
        user_id="u1",
    )

    assert gate["needs_reasoning"] is False
    assert gate["needs_memory"] is False
    assert gate["needs_tools"] is False


@pytest.mark.asyncio
async def test_select_tool_normalizes_use_tool_string_false(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore())

    async def fake_call_json(messages, user_config=None, user_id=None):
        return {
            "use_tool": "false",
            "tool_type": "mcp",
            "service_name": "search",
            "tool_name": "web_search",
            "args": {"q": "test"},
        }

    monkeypatch.setattr(svc, "_call_json", fake_call_json)

    selected = await svc._select_tool(
        step={"title": "lookup", "goal": "find data"},
        user_message="please find data",
        observations=[],
        catalog=[
            {
                "tool_type": "mcp",
                "service_name": "search",
                "tool_name": "web_search",
                "description": "search the web",
            }
        ],
        user_config={"reasoning": {"enabled": True}},
        user_id="u1",
    )

    assert selected["use_tool"] is False


@pytest.mark.asyncio
async def test_assess_outcome_records_on_confident_success(monkeypatch):
    tmpl = DummyTemplateMemory()
    svc = ReasoningService(conversation_core=DummyConversationCore(), template_memory=tmpl)

    svc._pending_outcomes["t1"] = {
        "user_id": "u1",
        "session_id": "s1",
        "user_message": "task",
        "gate": {},
        "policy": {},
        "tree": {"stats": {}, "nodes": []},
    }

    async def fake_judge(**kwargs):
        return {"outcome": "success", "confidence": 0.9, "reason": "ok"}

    monkeypatch.setattr(svc, "_judge_task_success", fake_judge)

    result = await svc.assess_outcome(
        tree_id="t1",
        assistant_output="answer",
        user_config={},
        user_id="u1",
        allow_human_review=True,
    )

    assert result["status"] == "recorded"
    assert len(tmpl.saved) == 1


@pytest.mark.asyncio
async def test_assess_outcome_requires_confirmation_on_unsure(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore(), template_memory=DummyTemplateMemory())

    svc._pending_outcomes["t2"] = {
        "user_id": "u1",
        "session_id": "s2",
        "user_message": "task",
        "gate": {},
        "policy": {},
        "tree": {"stats": {}, "nodes": []},
    }

    async def fake_judge(**kwargs):
        return {"outcome": "unsure", "confidence": 0.4, "reason": "not sure"}

    monkeypatch.setattr(svc, "_judge_task_success", fake_judge)

    result = await svc.assess_outcome(
        tree_id="t2",
        assistant_output="answer",
        user_config={},
        user_id="u1",
        allow_human_review=True,
    )

    assert result["status"] == "needs_confirmation"
    assert result["review_id"]


class DummyToolService:
    def __init__(self):
        self.calls = []

    async def call_tool(self, tool_name, params, ctx=None, request_id=None, connection_id=None, run_context=None, user_config=None):
        self.calls.append(
            {
                "tool_name": tool_name,
                "params": params,
                "request_id": request_id,
                "ctx": ctx,
            }
        )
        return {"run_id": "wf_test"}


@pytest.mark.asyncio
async def test_resolve_policy_normalizes_moirai_flags():
    svc = ReasoningService(conversation_core=DummyConversationCore())
    policy = svc._resolve_policy(
        user_id="u1",
        user_config={
            "reasoning": {
                "enabled": True,
                "moirai_export_plan": "true",
                "moirai_auto_start": "0",
            }
        },
    )

    assert policy["moirai_export_plan"] is True
    assert policy["moirai_auto_start"] is False


@pytest.mark.asyncio
async def test_run_exports_plan_to_moirai_when_enabled(monkeypatch):
    tool_service = DummyToolService()
    svc = ReasoningService(conversation_core=DummyConversationCore(), tool_service=tool_service)

    async def fake_gate(**kwargs):
        return {
            "needs_reasoning": False,
            "needs_memory": False,
            "needs_tools": True,
            "complexity": "low",
            "reason": "test",
        }

    async def fake_execute_step(**kwargs):
        return []

    async def fake_summarize_tree(**kwargs):
        return ""

    monkeypatch.setattr(svc, "_gate_reasoning", fake_gate)
    monkeypatch.setattr(svc, "_execute_step", fake_execute_step)
    monkeypatch.setattr(svc, "_summarize_tree", fake_summarize_tree)

    result = await svc.run(
        session_id="s1",
        user_id="u1",
        user_message="help me with tooling",
        recent_messages=[],
        base_system_prompt="You are helpful.",
        user_config={
            "reasoning": {
                "enabled": True,
                "moirai_export_plan": True,
                "moirai_auto_start": False,
            }
        },
    )

    assert result["used_reasoning"] is True
    assert result["moirai_run_id"] == "wf_test"
    assert len(tool_service.calls) == 1
    call = tool_service.calls[0]
    assert call["tool_name"] == "create_flow"
    assert call["params"]["service_name"] == "moirai"
    assert call["params"]["tool_name"] == "create_flow"

@pytest.mark.asyncio
async def test_select_tool_falls_back_to_strategy_when_llm_choice_invalid(monkeypatch):
    svc = ReasoningService(conversation_core=DummyConversationCore())

    async def fake_call_json(messages, user_config=None, user_id=None):
        return {
            "use_tool": True,
            "service_name": "non_exist",
            "tool_name": "missing",
            "args": {},
        }

    monkeypatch.setattr(svc, "_call_json", fake_call_json)

    selected = await svc._select_tool(
        step={"title": "download", "goal": "open website and click download"},
        user_message="open the download website",
        observations=[],
        catalog=[
            {
                "tool_type": "mcp",
                "service_name": "computer_control",
                "tool_name": "browser_action",
                "description": "browser goto click type",
            }
        ],
        user_config={"reasoning": {"enabled": True}},
        user_id="u1",
    )

    assert selected["use_tool"] is True
    assert selected["service_name"] == "computer_control"
    assert selected["tool_name"] == "browser_action"


