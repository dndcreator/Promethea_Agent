import asyncio
import json
import time

import pytest

from gateway.action.model_action import AnswerDeltaProjector, InvalidModelAction, parse_model_action
from gateway.action.service import ActionService


class _Core:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    async def call_llm(self, messages, **_kwargs):
        self.messages.append([dict(item) for item in messages])
        response = self.responses.pop(0)
        if callable(response):
            response = response(messages)
        return {"status": "success", **response}


def _answer(messages):
    observation = json.loads(messages[-1]["content"][0]["text"])
    observation_id = observation["observation_id"]
    return {
        "content": json.dumps(
            {"action": "answer", "content": "verified", "evidence_refs": [observation_id]}
        )
    }


def test_canonical_model_action_supports_batches_without_claiming_plain_text():
    action = parse_model_action(
        '{"action":"tool_calls","calls":['
        '{"id":"one","tool_name":"web.fetch","args":{"url":"https://example.com"}},'
        '{"id":"two","tool_name":"math.calculate","args":{"expression":"2+2"}}]}'
    )
    assert action.kind == "tool_calls"
    assert [call.call_id for call in action.calls] == ["one", "two"]
    assert action.calls[0].arguments == {"url": "https://example.com"}

    answer = parse_model_action('{"action":"answer","content":"x"}')
    assert answer.kind == "answer"
    assert answer.content == "x"

    with pytest.raises(InvalidModelAction):
        parse_model_action('I will call a tool. {"action":"answer","content":"x"}')

    projector = AnswerDeltaProjector()
    assert projector.feed('<|DSML|> invoke name="memory.list_entries"') == ""


def test_canonical_model_action_supports_capability_intent():
    action = parse_model_action(
        '{"action":"capability_request","objective":"observe the live desktop",'
        '"required_capabilities":["computer.screen"],"preferred_modalities":["vision"],'
        '"max_side_effect":"read_only"}'
    )
    assert action.kind == "capability_request"
    assert action.capability_request is not None
    assert action.capability_request.required_capabilities == ["computer.screen"]
    assert action.capability_request.max_side_effect == "read_only"


@pytest.mark.asyncio
async def test_action_service_executes_independent_calls_concurrently():
    from types import SimpleNamespace
    from gateway.tools.registry import ToolRegistry
    from gateway.tools.spec import ToolSpec

    registry = ToolRegistry()
    for name in ("a", "b"):
        registry.register_spec(ToolSpec(tool_name=name, concurrency_safe=True))
    core = _Core([
        {
            "content": (
                '{"action":"tool_calls","calls":['
                '{"id":"one","tool_name":"a","args":{}},'
                '{"id":"two","tool_name":"b","args":{}}]}'
            )
        },
        _answer,
    ])

    entered = set()
    both_entered = asyncio.Event()

    async def executor(_name, _args):
        entered.add(_name)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        return {"ok": True}

    out = await ActionService(conversation_core=core, capability_service=SimpleNamespace(tool_registry=registry)).run_action(
        goal="parallel",
        messages=[{"role": "user", "content": "parallel"}],
        tool_executor=executor,
        budget=3,
    )

    assert entered == {"a", "b"}
    assert out["status"] == "success"
    assert len(out["observations"]) == 2


@pytest.mark.asyncio
async def test_plain_text_is_not_committed_and_gets_protocol_retry():
    core = _Core([
        {"content": "I would call math.calculate."},
        {"content": '{"action":"answer","content":"I would call math.calculate."}'},
    ])

    out = await ActionService(conversation_core=core).run_action(
        goal="calculate",
        messages=[{"role": "user", "content": "calculate"}],
        budget=3,
    )

    assert out["content"] == "I would call math.calculate."
    assert len(core.messages) == 2


@pytest.mark.asyncio
async def test_malformed_runtime_action_gets_one_protocol_retry():
    core = _Core([
        {"content": '{"action":"tool_call","tool_name":'},
        {"content": '{"action":"answer","content":"I could not complete the tool call."}'},
    ])

    out = await ActionService(conversation_core=core).run_action(
        goal="calculate",
        messages=[{"role": "user", "content": "calculate"}],
        budget=3,
    )

    assert out["content"] == "I could not complete the tool call."
    retry = "\n".join(str(item.get("content") or "") for item in core.messages[1])
    assert "valid JSON runtime action" in retry
    assert '{"action":"tool_call","tool_name":' not in retry


@pytest.mark.asyncio
async def test_provider_control_syntax_never_becomes_user_reply():
    core = _Core([
        {"content": '{"action":"tool_call","tool_name":"memory.get_context","args":{"query":"work"}}'},
        {"content": '<|DSML|> calls\n<|DSML|> invoke name="memory.list_entries"'},
        {"content": '{"action":"answer","content":"I found the previous work."}'},
    ])
    streamed = []

    async def executor(_name, _args):
        return {"context": "previous work"}

    async def sink(delta):
        streamed.append(delta)

    out = await ActionService(conversation_core=core).run_action(
        goal="continue work",
        messages=[{"role": "user", "content": "continue"}],
        tool_executor=executor,
        budget=4,
        output_sink=sink,
    )

    assert out["status"] == "success"
    assert out["content"] == "I found the previous work."
    assert "DSML" not in "".join(streamed)


@pytest.mark.asyncio
async def test_repeated_untyped_output_fails_without_assistant_content():
    core = _Core([
        {"content": '<|DSML|> invoke name="memory.list_entries"'},
        {"content": "still not a canonical action"},
    ])

    out = await ActionService(conversation_core=core).run_action(
        goal="continue work",
        messages=[{"role": "user", "content": "continue"}],
        budget=3,
    )

    assert out["status"] == "error"
    assert out["content"] == ""
    assert out["action_state"]["phase"] == "failed"
