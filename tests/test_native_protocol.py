from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.action.model_action import InvalidModelAction, parse_model_action
from gateway.tool_prompt_blocks import build_action_protocol_prompt
from tests.support.evaluation import Budget, journal_exposure
from tests.support.native_protocol import NativeTranscript, decode_native, native_functions
from tests.support.protocol_eval import NativeEndpoint, protocol_case
from tests.support.runtime import ScriptedModel


def call(kind, args, identifier="call_one"):
    return {"id": identifier, "type": "function", "function": {"name": kind, "arguments": json.dumps(args)}}


def wire(action):
    action = dict(action)
    kind = action.pop("action")
    return {"role": "assistant", "content": "", "reasoning_content": "provider reasoning retained for wire replay", "tool_calls": [call(kind, action)]}


def endpoint(monkeypatch, actions, root):
    import openai
    messages, responses = [], iter(actions)

    async def create(**params):
        messages.append(deepcopy(params))
        value = next(responses)
        message = SimpleNamespace(content=value.get("content"), reasoning_content=value.get("reasoning_content"), model_dump=lambda **_: deepcopy(value))
        return SimpleNamespace(id=f"response_{len(messages)}", model="fixture", usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 100, "completion_tokens": 50}),
                               choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if value.get("tool_calls") else "stop")])

    async def close():
        pass

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close))
    instance = NativeEndpoint({"PROMETHEA_EVAL_AGENT_MODEL": "fixture", "PROMETHEA_EVAL_AGENT_BASE_URL": "https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY": "fake"},
                              Budget(max_cost_usd=0.5, max_tokens=200000), (0.3, 1.2), journal_path=root / "requests.jsonl", max_request_cost_usd=0.03)
    return instance, messages


@pytest.mark.parametrize("action", [
    {"action": "answer", "content": "READY", "evidence_refs": []},
    {"action": "await_user", "content": "Please complete verification", "input_kind": "acknowledgement"},
    {"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "a.txt"}},
    {"action": "tool_calls", "calls": [{"id": "one", "tool_name": "workspace.read_file", "args": {"path": "a.txt"}}]},
    {"action": "capability_inspect", "capability_names": ["workspace.read_file"]},
    {"action": "capability_request", "objective": "read", "required_capabilities": ["workspace"], "max_side_effect": "read_only"},
])
def test_native_actions_reuse_canonical_validation(action):
    decoded, bindings = decode_native(wire(action))
    result = parse_model_action(json.dumps(decoded))
    assert result.kind == parse_model_action(json.dumps(action)).kind
    assert len(bindings) == 1


@pytest.mark.parametrize("message", [
    {"tool_calls": [call("unknown", {})]},
    {"tool_calls": [call("answer", {"content": "x"}), call("tool_call", {"tool_name": "write", "args": {}}, "second")]},
    {"tool_calls": [call("tool_call", {"tool_name": "write", "args": {}}), call("tool_call", {"tool_name": "write", "args": {}})]},
    {"tool_calls": [{"id": "x", "type": "function", "function": {"name": "tool_call", "arguments": '{"tool_name":"write","args":{"x":1,"x":2}}'}}]},
    {"tool_calls": [call("tool_call", {"action": "answer", "tool_name": "write", "args": {}})]},
    {"content": "<calls>provider control syntax</calls>"},
])
def test_native_ambiguity_and_control_syntax_never_become_executable_or_user_prose(message):
    with pytest.raises(InvalidModelAction):
        decode_native(message)


def test_native_batch_preserves_native_ids_and_shared_metadata():
    packet = {"tool_calls": [call("tool_call", {"tool_name": "read", "args": {"p": 1}, "procedure_refs": ["rule@1"]}, "one"),
                             call("tool_call", {"tool_name": "read", "args": {"p": 2}}, "two")]}
    decoded, bindings = decode_native(packet)
    assert bindings == {"one": ["one"], "two": ["two"]}
    assert [row["id"] for row in decoded["calls"]] == ["one", "two"]
    assert decoded["procedure_refs"] == ["rule@1"]
    with pytest.raises(InvalidModelAction, match="disabled"):
        decode_native(packet, final=True)
    assert {row["function"]["name"] for row in native_functions()} == {"answer", "tool_call", "tool_calls", "capability_request", "capability_inspect", "await_user"}
    assert "Return exactly one JSON" in build_action_protocol_prompt()
    assert "Return exactly one JSON" not in build_action_protocol_prompt(native=True)
    assert "capability operation with tool execution" not in build_action_protocol_prompt(native=True)
    assert "capability queries may share one response" in build_action_protocol_prompt(native=True)


def test_native_transcript_never_assigns_another_calls_failure_to_missing_receipt():
    transcript = NativeTranscript()
    initial = [{"role": "user", "content": "read both"}]
    transcript.prepare(initial)
    packet = {"role": "assistant", "tool_calls": [call("tool_call", {"tool_name": "read", "args": {}}, "one"),
                                                       call("tool_call", {"tool_name": "read", "args": {}}, "two")]}
    canonical, bindings = decode_native(packet)
    transcript.accept(packet, canonical, bindings)
    transcript.observations = [{"observation_id": "obs_one", "tool_call_id": "one", "ok": False}]
    fact = {"observation_id": "obs_one", "status": "failed", "error": {"code": "MISSING"}}
    messages = [*initial, {"role": "assistant", "content": json.dumps(canonical)}, {"role": "user", "content": [{"type": "text", "text": json.dumps(fact)}]}]
    with pytest.raises(ValueError, match="no committed"):
        transcript.prepare(messages)


@pytest.mark.asyncio
async def test_protocol_pilot_global_admission_stops_before_transport(tmp_path, monkeypatch):
    import openai
    from scripts.evaluate_protocol import run

    async def send(**_):
        raise AssertionError("no paid send permitted")
    async def close():
        pass
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=send)), close=close))
    env = tmp_path / ".env.eval"
    env.write_text("\n".join(["PROMETHEA_EVAL_AGENT_BASE_URL=https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY=fake", "PROMETHEA_EVAL_AGENT_MODEL=fixture",
                               "PROMETHEA_EVAL_AGENT_INPUT_USD_PER_MILLION=0.3", "PROMETHEA_EVAL_AGENT_OUTPUT_USD_PER_MILLION=1.2", "PROMETHEA_EVAL_MAX_COST_USD=0.5"]), encoding="utf-8")
    report = await run(tmp_path / "result", env, 0.000000001, 0.03, 20261031)
    assert report["calls"] == 0 and report["paired_cases"] == [] and report["stop_reason"]
    assert report["exposure_upper_usd"] == 0 and not report["cases"][0]["evaluation_complete"]


TRACES = {
    "direct": [{"action": "answer", "content": "READY"}],
    "arithmetic": [{"action": "answer", "content": "323"}],
    "write": [{"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "note.txt", "content": "ORCHID-29"}}],
    "read": [{"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "code.txt"}}, {"action": "answer", "content": "ECHO-31"}],
    "write-two": [{"action": "tool_calls", "calls": [{"tool_name": "workspace.write_file", "args": {"path": name, "content": value}} for name, value in [("a.txt", "ALPHA"), ("b.txt", "BETA")]]}],
    "read-two": [{"action": "tool_calls", "calls": [{"tool_name": "workspace.read_file", "args": {"path": name}} for name in ["a.txt", "b.txt"]]}, {"action": "answer", "content": "LIME-17 PLUM-42"}],
    "recover-missing": [{"action": "tool_call", "tool_name": "workspace.read_file", "args": {"path": "missing.txt"}}, {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "missing.txt", "content": "RECOVERED"}}],
    "inspect": [{"action": "capability_inspect", "capability_names": ["workspace.write_file"]}, {"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "schema.txt", "content": "CHECKED"}}],
    "resolve": [{"action": "capability_request", "objective": "check availability", "required_capabilities": ["fixture.absent"], "max_side_effect": "read_only"}, {"action": "answer", "content": "No candidate is available."}],
    "approval": [{"action": "tool_call", "tool_name": "fixture.send", "args": {"text": "HELLO"}}],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["prompt_json", "native"])
async def test_all_ten_protocol_cases_use_real_runtime_and_preserve_safety(tmp_path, monkeypatch, mode):
    corpus = json.loads((Path(__file__).parent / "evaluation/protocol-live.json").read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        root = tmp_path / case["id"]
        root.mkdir()
        actions = deepcopy(TRACES[case["id"]])
        if actions[-1]["action"] != "answer" and case["id"] != "approval":
            actions.append({"action": "answer", "content": "Done."})
        if mode == "native":
            model, sent = endpoint(monkeypatch, [wire(action) for action in actions], root)
        else:
            model = ScriptedModel(actions)
        row = await protocol_case(case, model, root, mode)
        assert row["passed"], row
        assert row["unsafe_dispatches"] == 0
        if mode == "native":
            assert journal_exposure(root / "requests.jsonl")["unresolved_requests"] == 0
            if len(sent) > 1:
                assert any(message.get("role") == "tool" for message in sent[-1]["messages"])
                assert any(message.get("reasoning_content") for message in sent[-1]["messages"])
