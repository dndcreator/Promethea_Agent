from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.state_machine import ActionPhase, InvalidActionTransition, RuntimeActionStateMachine
from gateway.conversation_service import ConversationService


class _Core:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def call_llm(self, messages, user_config=None, user_id=None):
        self.calls.append({"messages": list(messages), "user_config": user_config, "user_id": user_id})
        response = self.responses.pop(0)
        if callable(response):
            response = response(messages)
        return {"status": "success", "usage": {"prompt_tokens": 3, "completion_tokens": 2}, **response}


@pytest.mark.asyncio
async def test_provider_output_limit_is_not_retried_as_a_protocol_parse_error():
    class Core:
        calls = 0

        async def call_llm_stream(self, *args, reasoning_sink=None, result_sink=None, **kwargs):
            self.calls += 1
            await reasoning_sink("plan the application")
            await result_sink({"status": "error", "code": "MODEL_OUTPUT_LIMIT", "finish_reason": "length", "usage": {"completion_tokens": 2000}})
            yield "[error] MODEL_OUTPUT_LIMIT"

    async def publish(_):
        pass

    core = Core()
    result = await ActionService(conversation_core=core).run_action(goal="Create UI", messages=[], output_sink=publish, budget=2)
    assert core.calls == 3
    assert result["status"] == "error" and result["content"] == ""
    assert result["error"]["code"] == "MODEL_OUTPUT_LIMIT"
    assert [item["error"]["code"] for item in result["observations"]] == [
        "MODEL_OUTPUT_LIMIT", "MODEL_OUTPUT_LIMIT", "ACTION_BUDGET_EXHAUSTED",
    ]
    assert result["reasoning_steps"][0]["content"] == "plan the application"
    assert result["usage"]["completion_tokens"] == 6000


def _answer_from_observations(messages):
    observation = json.loads(messages[-1]["content"][0]["text"])
    observation_id = observation["observation_id"]
    return {
        "content": json.dumps(
            {"action": "answer", "content": "action complete", "evidence_refs": [observation_id]}
        )
    }


@pytest.mark.asyncio
async def test_action_service_owns_model_action_state_machine():
    core = _Core([{"content": '{"action":"answer","content":"done"}'}])
    service = ActionService(conversation_core=core)

    out = await service.run_action(
        goal="answer directly",
        messages=[{"role": "user", "content": "answer directly"}],
        session_id="s1",
        user_id="u1",
        budget=3,
    )

    assert out["status"] == "success"
    assert out["content"] == "done"
    assert out["action_state"]["phase"] == ActionPhase.COMPLETED.value
    assert out["action_run_id"].startswith("act_")
    assert core.calls[0]["messages"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_plain_model_text_requires_a_canonical_answer_before_commit():
    core = _Core([
        {"content": "This is the final answer."},
        {"content": '{"action":"answer","content":"This is the final answer."}'},
    ])

    out = await ActionService(conversation_core=core).run_action(
        goal="answer directly",
        messages=[{"role": "user", "content": "answer directly"}],
    )

    assert out["status"] == "success"
    assert out["content"] == "This is the final answer."
    assert out["action_state"]["phase"] == ActionPhase.COMPLETED.value


@pytest.mark.asyncio
async def test_plain_model_text_after_tool_observation_is_retried_before_commit():
    core = _Core([
        {"content": '{"action":"tool_call","id":"c1","tool_name":"math.calculate","args":{"expression":"2+2"}}'},
        {"content": "The result is 4."},
        {"content": '{"action":"answer","content":"The result is 4."}'},
    ])

    out = await ActionService(conversation_core=core).run_action(
        goal="calculate",
        messages=[{"role": "user", "content": "calculate 2+2"}],
        tool_executor=lambda *_: {"value": 4},
        budget=3,
    )

    assert out["status"] == "success"
    assert out["content"] == "The result is 4."
    assert [item["tool_name"] for item in out["observations"]] == ["math.calculate", "runtime.model_action"]


@pytest.mark.asyncio
async def test_action_service_executes_batch_and_commits_observations():
    core = _Core([
        {
            "content": json.dumps(
                {
                    "action": "tool_calls",
                    "calls": [
                        {"id": "c1", "tool_name": "math.calculate", "args": {"expression": "2+2"}},
                        {"id": "c2", "tool_name": "utils.now", "args": {}},
                    ],
                }
            )
        },
        _answer_from_observations,
    ])
    executed = []
    context = SimpleNamespace(
        task_id="task-1",
        task_run_id="task-run-1",
        workflow_run_id=None,
        conversation_turn_id="turn-1",
    )

    async def executor(name, args):
        executed.append((name, args))
        return {"ok": True, "name": name}

    out = await ActionService(conversation_core=core).run_action(
        goal="run tools",
        messages=[{"role": "user", "content": "run tools"}],
        session_id="session-1",
        user_id="user-1",
        run_context=context,
        tool_executor=executor,
        budget=3,
    )

    assert out["status"] == "success"
    assert [name for name, _ in executed] == ["math.calculate", "utils.now"]
    assert len(out["observations"]) == 2
    assert all(item["action_loop_id"] == out["action_run_id"] for item in out["observations"])
    visible_fact = json.loads(core.calls[1]["messages"][-1]["content"][0]["text"])
    assert visible_fact["subject"] == "math.calculate"
    assert visible_fact["scope"] == {
        "action_loop_id": out["action_run_id"],
        "conversation_turn_id": "turn-1",
        "session_id": "session-1",
        "task_id": "task-1",
        "task_run_id": "task-run-1",
        "user_id": "user-1",
    }
    assert "Decide the next action" not in json.dumps(core.calls[1]["messages"][-1]["content"])


@pytest.mark.asyncio
async def test_action_service_resolves_capability_before_binding_tool():
    def choose_resolved_tool(messages):
        observation = json.loads(messages[-1]["content"][0]["text"])
        assert observation["subject"] == "runtime.capability_resolve"
        return {
            "content": json.dumps(
                {
                    "action": "tool_call",
                    "id": "screen-1",
                    "tool_name": "computer_control.screen_action",
                    "procedure_refs": ["process-1:2"],
                    "args": {"action": "screenshot"},
                }
            )
        }

    core = _Core([
        {
            "content": json.dumps(
                {
                    "action": "capability_request",
                    "objective": "observe the live desktop",
                    "required_capabilities": ["computer.screen"],
                    "preferred_modalities": ["vision"],
                    "max_side_effect": "read_only",
                }
            )
        },
        choose_resolved_tool,
        _answer_from_observations,
    ])

    async def resolver(intent):
        assert intent["required_capabilities"] == ["computer.screen"]
        return {
            "candidate_count": 1,
            "candidates": [{"name": "computer_control.screen_action", "input_schema": {}}],
            "process_experience": {"rules": [{"reference": "process-1:2"}]},
        }

    out = await ActionService(conversation_core=core).run_action(
        goal="look at desktop",
        messages=[{"role": "user", "content": "look at desktop"}],
        capability_resolver=resolver,
        tool_executor=lambda *_: {"screenshot": "captured"},
        budget=4,
    )

    assert out["status"] == "success"
    assert [item["kind"] for item in out["execution_path"]] == ["capability_request", "tool_call"]
    assert out["execution_path"][1]["tool_name"] == "computer_control.screen_action"
    assert out["execution_path"][1]["procedure_refs"] == ["process-1:2"]


@pytest.mark.asyncio
async def test_unknown_procedure_reference_uses_protocol_recovery_not_execution():
    core = _Core([
        {"content": '{"action":"tool_call","tool_name":"test.run","args":{},"procedure_refs":["invented:1"]}'},
        {"content": '{"action":"answer","content":"replanned"}'},
    ])
    executed = []
    out = await ActionService(conversation_core=core).run_action(
        goal="inspect", messages=[{"role": "user", "content": "inspect"}],
        tool_executor=lambda *args: executed.append(args), budget=3,
    )
    assert out["status"] == "success"
    assert out["content"] == "replanned"
    assert executed == []


@pytest.mark.asyncio
async def test_waiting_confirmation_resumes_same_action_loop():
    core = _Core([
        {"content": '{"action":"tool_call","id":"c1","tool_name":"workspace.write_file","args":{"path":"a.txt","content":"x"}}'},
        _answer_from_observations,
    ])
    service = ActionService(conversation_core=core)
    context = SimpleNamespace(action_loop_id=None, action_state=None)

    pending = await service.run_action(
        goal="write file",
        messages=[{"role": "user", "content": "write file"}],
        run_context=context,
        tool_executor=lambda *_: {"ok": True},
        confirmation_resolver=lambda *_: True,
        budget=3,
    )
    assert pending["status"] == "needs_confirmation"
    assert pending["action_state"]["phase"] == ActionPhase.WAITING_CONFIRMATION.value

    resumed = await service.resume_action(
        pending=pending,
        approved_call_id="c1",
        user_config=None,
        session_id="s1",
        user_id="u1",
        run_context=context,
        tool_executor=lambda *_: {"ok": True},
        confirmation_resolver=lambda *_: True,
    )

    assert resumed["status"] == "success"
    assert resumed["action_run_id"] == pending["action_run_id"]
    assert resumed["action_state"]["phase"] == ActionPhase.COMPLETED.value
    assert resumed["usage"]["prompt_tokens"] == 6
    assert resumed["usage"]["completion_tokens"] == 4
    assert any(row["from"] == "waiting_confirmation" and row["to"] == "validating" for row in resumed["action_state_transitions"])


@pytest.mark.asyncio
async def test_rejected_confirmation_becomes_observation_and_agent_finishes_turn():
    core = _Core([
        {"content": '{"action":"tool_call","id":"c1","tool_name":"workspace.write_file","args":{"path":"a.txt","content":"x"}}'},
        _answer_from_observations,
    ])
    service = ActionService(conversation_core=core)
    executed = []
    pending = await service.run_action(
        goal="write file",
        messages=[{"role": "user", "content": "write file"}],
        tool_executor=lambda *args: executed.append(args),
        confirmation_resolver=lambda *_: True,
        budget=3,
    )

    rejected = await service.reject_pending_action(
        pending=pending,
        user_config=None,
        session_id="s1",
        user_id="u1",
        run_context=None,
        tool_executor=lambda *args: executed.append(args),
        confirmation_resolver=lambda *_: True,
    )

    assert rejected["status"] == "success"
    assert rejected["content"] == "action complete"
    assert executed == []
    assert rejected["observations"][-1]["error"]["code"] == "USER_DECLINED"
    assert rejected["execution_path"][-1]["executed"] is False
    assert rejected["execution_path"][-1]["observation_id"] == rejected["observations"][-1]["observation_id"]
    assert rejected["action_state"]["phase"] == ActionPhase.COMPLETED.value
    assert any(
        row["from"] == "waiting_confirmation" and row["to"] == "observing"
        for row in rejected["action_state_transitions"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_resumed_batch_uses_normal_failure_and_cancellation_boundary(cancel):
    core = _Core([
        {"content": '{"action":"tool_call","id":"c1","tool_name":"workspace.write_file","args":{}}'},
        {"content": '{"action":"answer","content":"Authorization is unavailable; nothing was executed."}'},
    ])
    service = ActionService(conversation_core=core)
    context = SimpleNamespace(action_loop_id=None, action_state=None)
    pending = await service.run_action(
        goal="write", messages=[], run_context=context,
        confirmation_resolver=lambda *_: True,
    )
    entered = asyncio.Event()

    async def executor(*_):
        entered.set()
        await asyncio.Event().wait()

    def policy(*_):
        raise RuntimeError("policy unavailable")

    # A second call still needs a policy check after the first approval.
    if not cancel:
        pending["pending_tool_calls"].append({"id": "c2", "name": "workspace.write_file", "args": {}})
    task = asyncio.create_task(service.resume_action(
        pending=pending, approved_call_id="c1", user_config=None,
        session_id="s", user_id="u", run_context=context,
        tool_executor=executor, confirmation_resolver=policy,
    ))
    if cancel:
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert context.action_state["phase"] == "cancelled"
    else:
        result = await task
        assert result["status"] == "success"
        assert result["content"] == "Authorization is unavailable; nothing was executed."
        assert all(item["error"]["code"] == "TOOL_AUTHORIZATION_UNAVAILABLE" for item in result["observations"])
        assert all(not item["executed"] for item in result["execution_path"])
        assert not entered.is_set()


@pytest.mark.asyncio
async def test_conversation_service_delegates_to_action_service():
    core = _Core([{"content": '{"action":"answer","content":"action complete"}'}])
    action = ActionService(conversation_core=core)
    conversation = ConversationService(conversation_core=core, action_service=action)

    out = await conversation.run_chat_loop(
        [{"role": "user", "content": "find current data"}],
        session_id="s1",
        user_id="u1",
        max_recursion=3,
    )

    assert out["content"] == "action complete"
    assert out["action_state"]["phase"] == "completed"
    assert "Runtime action protocol:" in core.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_provider_failure_is_runtime_failure_without_protocol_retry():
    class _FailedCore:
        def __init__(self):
            self.calls = 0

        async def call_llm(self, *_args, **_kwargs):
            self.calls += 1
            return {"status": "error", "content": "provider unavailable"}

    core = _FailedCore()
    result = await ActionService(conversation_core=core).run_action(
        goal="answer",
        messages=[{"role": "user", "content": "answer"}],
    )
    assert result["status"] == "error"
    assert result["content"] == ""
    assert result["error"]["message"] == "provider unavailable"
    assert core.calls == 1


@pytest.mark.asyncio
async def test_runtime_failure_never_fabricates_an_agent_reply():
    class BrokenCore:
        async def call_llm(self, *_args, **_kwargs):
            raise RuntimeError("model transport unavailable")

    result = await ActionService(conversation_core=BrokenCore()).run_action(
        goal="run missing tool",
        messages=[{"role": "user", "content": "run it"}],
    )

    assert result["status"] == "error"
    assert result["content"] == ""
    assert result["error"]["type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_action_service_streams_only_answer_content_from_canonical_action():
    class _StreamingCore:
        async def call_llm_stream(self, *_args, **_kwargs):
            for chunk in ('{"action":"answer","content":"hel', 'lo\\nworld"}'):
                yield chunk

    deltas = []

    async def sink(delta):
        deltas.append(delta)

    result = await ActionService(conversation_core=_StreamingCore()).run_action(
        goal="answer",
        messages=[{"role": "user", "content": "answer"}],
        output_sink=sink,
    )

    assert result["status"] == "success"
    assert result["content"] == "hello\nworld"
    assert "".join(deltas) == result["content"]


@pytest.mark.asyncio
async def test_action_service_streams_and_persists_provider_reasoning_by_model_step():
    class _StreamingCore:
        async def call_llm_stream(self, *_args, reasoning_sink=None, **_kwargs):
            await reasoning_sink("check ")
            await reasoning_sink("facts")
            yield '{"action":"answer","content":"done"}'

    events = []

    async def reasoning_sink(payload):
        events.append(payload)

    async def output_sink(_delta):
        return None

    result = await ActionService(conversation_core=_StreamingCore()).run_action(
        goal="answer",
        messages=[{"role": "user", "content": "answer"}],
        output_sink=output_sink,
        reasoning_sink=reasoning_sink,
    )

    assert "".join(item["delta"] for item in events) == "check facts"
    assert len({item["step_id"] for item in events}) == 1
    assert result["reasoning_steps"][0]["content"] == "check facts"


@pytest.mark.asyncio
async def test_action_service_does_not_stream_plain_untyped_output():
    class _StreamingCore:
        def __init__(self):
            self.calls = 0

        async def call_llm_stream(self, *_args, **_kwargs):
            self.calls += 1
            chunks = (
                ("plain ", "answer")
                if self.calls == 1
                else ('{"action":"answer","content":"plain ', 'answer"}')
            )
            for chunk in chunks:
                yield chunk

    deltas = []

    async def sink(delta):
        deltas.append(delta)

    result = await ActionService(conversation_core=_StreamingCore()).run_action(
        goal="answer",
        messages=[{"role": "user", "content": "answer"}],
        output_sink=sink,
    )

    assert result["status"] == "success"
    assert result["content"] == "plain answer"
    assert "".join(deltas) == result["content"]


@pytest.mark.asyncio
async def test_answer_stream_preserves_split_unicode_escape_pair():
    class _StreamingCore:
        async def call_llm_stream(self, *_args, **_kwargs):
            for chunk in ('{"action":"answer","content":"A\\ud83d', '\\ude00B"}'):
                yield chunk

    deltas = []

    async def sink(delta):
        deltas.append(delta)

    result = await ActionService(conversation_core=_StreamingCore()).run_action(
        goal="answer",
        messages=[{"role": "user", "content": "answer"}],
        output_sink=sink,
    )

    assert result["content"] == "A😀B"
    assert "".join(deltas) == "A😀B"


@pytest.mark.asyncio
async def test_capability_inspection_error_cannot_be_committed_as_success():
    core = _Core([
        {"content": '{"action":"capability_inspect","capability_names":["missing.tool"]}'},
        {"content": '{"action":"answer","content":"I cannot inspect that capability right now."}'},
    ])

    async def failed_inspection(_names):
        return {"error": "registry unavailable"}

    result = await ActionService(conversation_core=core).run_action(
        goal="inspect",
        messages=[{"role": "user", "content": "inspect"}],
        capability_inspector=failed_inspection,
    )

    assert result["status"] == "success"
    assert result["observations"][0]["ok"] is False
    assert result["action_state"]["phase"] == "completed"


@pytest.mark.asyncio
async def test_runtime_cancellation_commits_cancelled_state():
    release = asyncio.Event()

    class _BlockingCore:
        async def call_llm(self, *_args, **_kwargs):
            await release.wait()

    context = SimpleNamespace(action_loop_id=None, action_state=None)
    task = asyncio.create_task(
        ActionService(conversation_core=_BlockingCore()).run_action(
            goal="wait",
            messages=[{"role": "user", "content": "wait"}],
            run_context=context,
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert context.action_state["phase"] == "cancelled"


def test_state_restore_rejects_inconsistent_history():
    with pytest.raises(InvalidActionTransition, match="source"):
        RuntimeActionStateMachine.restore(
            [{"revision": 1, "from": "executing", "to": "awaiting_model", "cause": "tampered"}]
        )
