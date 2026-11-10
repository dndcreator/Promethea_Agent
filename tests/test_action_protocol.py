import json
from pathlib import Path

import pytest

from gateway.action import ActionService
from gateway.action.models import ActionContext, ActionRun
from gateway.action.checkpoint import capture, restore
from gateway.action.completion import parse_final_answer
from gateway.action.model_action import InvalidModelAction, parse_model_action
from gateway.action.recovery import recover, reset_failures
from gateway.protocol import EventType
from tests.support.runtime import ScriptedModel, runtime_at


@pytest.mark.parametrize("opening", ["```json", "```JSON", "```"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_complete_single_fence_preserves_exact_arguments_and_batch_ids(opening, newline):
    value = 'line\n```json\n{example}\n```\r\n\u2028🙂'
    action = {"action": "tool_calls", "calls": [{"id": "one", "tool_name": "files.write", "args": {"content": value}},
                                                   {"id": "two", "tool_name": "files.read", "args": {}}]}
    parsed = parse_model_action(f" {opening}{newline}{json.dumps(action, ensure_ascii=False)}{newline}``` \n")
    assert parsed.calls[0].arguments["content"] == value
    assert [call.call_id for call in parsed.calls] == ["one", "two"]


@pytest.mark.parametrize("text,reason", [
    ('Here is the action:\n```json\n{"action":"answer","content":"x"}\n```', "JSON_ENVELOPE_INVALID"),
    ('```json\n{"action":"answer","content":"x"}\n```\nextra', "JSON_ENVELOPE_INVALID"),
    ('```python\n{"action":"answer","content":"x"}\n```', "JSON_ENVELOPE_INVALID"),
    ('```json\n{"action":"answer","content":"x"}', "JSON_ENVELOPE_INVALID"),
    ('```json\n{"action":"tool_call","tool_name":"write","args":{\n```', "JSON_ENVELOPE_INVALID"),
    ('{"action":"answer","content":"a"}\n{"action":"answer","content":"b"}', "MULTIPLE_ACTIONS"),
    ('```json\n{"action":"answer","content":"a"}\n{"action":"answer","content":"b"}\n```', "MULTIPLE_ACTIONS"),
    ('```json\n{"action":"answer","content":"a"}\n```\n```json\n{"action":"answer","content":"b"}\n```', "JSON_ENVELOPE_INVALID"),
    ('{"action":"tool_call","tool_name":"write","args":{"n":1,"n":2}}', "DUPLICATE_ACTION_FIELD"),
    ('{"action":"tool_call","tool_name":"write","args":{"n":NaN}}', "JSON_ENVELOPE_INVALID"),
    ('{"action":"tool_call","tool_name":"write","args":{"n":Infinity}}', "JSON_ENVELOPE_INVALID"),
    ('{"action":"tool_calls","calls":[]}', "ACTION_SCHEMA_INVALID"),
    ('[]', "ACTION_SCHEMA_INVALID"),
])
def test_ambiguity_truncation_duplicates_and_invalid_schema_remain_rejected(text, reason):
    with pytest.raises(InvalidModelAction) as caught:
        parse_model_action(text)
    assert caught.value.code == "INVALID_MODEL_ACTION"
    assert caught.value.reason == reason


def test_final_phase_accepts_fenced_answer_but_never_tool_or_batch_actions():
    assert parse_final_answer('```json\n{"action":"answer","content":"Progress retained."}\n```').content == "Progress retained."
    for action in ({"action": "tool_call", "tool_name": "delete", "args": {}},
                   {"action": "tool_calls", "calls": [{"tool_name": "delete", "args": {}}]}):
        with pytest.raises(InvalidModelAction, match="disabled"):
            parse_final_answer(f"```json\n{json.dumps(action)}\n```")


def test_error_families_are_independent_but_protocol_variants_share_one_budget():
    state = {}
    def fail(code, signature):
        return recover(state, code=code, signature=signature, initial=2000, ceiling=8192, retries=2)[0]
    assert fail("MODEL_OUTPUT_LIMIT", "cut")
    assert state["output_tokens"] == 4000
    assert fail("JSON_ENVELOPE_INVALID", "first")
    assert fail("MULTIPLE_ACTIONS", "second")
    assert fail("MODEL_OUTPUT_LIMIT", "cut-again")
    assert state["output_tokens"] == 8000
    assert not fail("ACTION_SCHEMA_INVALID", "third")
    assert state["families"]["protocol"]["failures"] == 3
    reset_failures(state)
    assert state == {"output_tokens": 8000}


@pytest.mark.asyncio
async def test_fenced_tool_executes_once_with_original_provider_audit_and_canonical_history(tmp_path):
    raw = '```json\n{"action":"tool_call","tool_name":"workspace.write_file","args":{"path":"result.txt","content":"ORCHID-29"}}\n```'
    model = ScriptedModel([raw, {"action": "answer", "content": "File retained."}])
    host = runtime_at(tmp_path, model)
    from gateway.protocol import RequestType
    response = await host.handle_http_request(method=RequestType.CHAT, params={"message": "Write result.txt", "session_id": "protocol"}, user_id="alice")
    assert response.ok
    handle = host.workspace_service.resolve_workspace_handle(user_id="alice", workspace_id="protocol")
    assert (Path(handle.root_path) / "result.txt").read_text(encoding="utf-8") == "ORCHID-29"
    observations = host.event_emitter.get_history(EventType.ACTION_OBSERVATION_COMMITTED)
    assert len([event for event in observations if event.payload["tool_name"] == "workspace.write_file"]) == 1
    manifests = host.event_emitter.get_history(EventType.MODEL_CALL_RECORDED)
    assert manifests[0].payload["response_content"] == raw
    action_message = next(row for row in model.calls[1] if row["role"] == "assistant")
    assert json.loads(action_message["content"])["tool_name"] == "workspace.write_file"


@pytest.mark.asyncio
async def test_truncated_even_complete_fenced_proposal_never_executes_and_total_steps_remain_bound():
    raw = '```json\n{"action":"tool_call","tool_name":"delete","args":{}}\n```'
    model = ScriptedModel([{"status": "error", "code": "MODEL_OUTPUT_LIMIT", "content": raw},
                           '{"action":"answer","content":"a"}{"action":"answer","content":"b"}',
                           {"action": "answer", "content": "Nothing executed."}])
    writes = []
    result = await ActionService(conversation_core=model).run_action(goal="act", messages=[], budget=2,
        tool_executor=lambda *args: writes.append(args))
    assert writes == [] and len(model.calls) == 3
    assert result["execution_outcome"]["stop_reason"] == "budget_exhausted"
    assert result["observations"][1]["error"]["details"]["reason"] == "MULTIPLE_ACTIONS"


@pytest.mark.asyncio
async def test_protocol_recovery_after_output_growth_is_not_preempted_by_shared_counter():
    model = ScriptedModel([{"status": "error", "code": "MODEL_OUTPUT_LIMIT", "content": "partial"},
                           '```json\n{"action":"answer","content":\n```',
                           '{"action":"answer","content":"a"}{"action":"answer","content":"b"}',
                           {"action": "answer", "content": "Recovered."}])
    result = await ActionService(conversation_core=model).run_action(goal="act", messages=[], budget=4)
    assert result["content"] == "Recovered." and result.get("execution_outcome") is None
    assert len(model.calls) == 4
    assert [row["error"].get("details", {}).get("reason") for row in result["observations"]] == [None, "JSON_ENVELOPE_INVALID", "MULTIPLE_ACTIONS"]


def test_family_counters_and_output_allowance_survive_checkpoint_roundtrip():
    context = ActionContext()
    run = ActionRun(goal="act", messages=[], context=context)
    recover(run.model_recovery, code="MODEL_OUTPUT_LIMIT", signature="cut", initial=2000, ceiling=8192, retries=2)
    recover(run.model_recovery, code="MULTIPLE_ACTIONS", signature="bad", initial=2000, ceiling=8192, retries=2)
    saved = capture(run, [], {})
    recovered = restore(saved, context)
    assert recovered.model_recovery == run.model_recovery
    assert recovered.model_recovery["families"]["protocol"]["failures"] == 1
    recovered.model_recovery["families"]["protocol"]["failures"] += 1
    assert saved["model_recovery"]["families"]["protocol"]["failures"] == 1


@pytest.mark.asyncio
async def test_fence_does_not_bypass_confirmation_or_leak_through_stream():
    calls = []
    raw = '```json\n{"action":"tool_call","tool_name":"sensitive","args":{}}\n```'
    result = await ActionService(conversation_core=ScriptedModel([raw])).run_action(
        goal="act", messages=[], confirmation_resolver=lambda *_: True, tool_executor=lambda *args: calls.append(args))
    assert calls == [] and result["status"] == "needs_confirmation"
    published = []
    async def sink(value):
        published.append(value)
    result = await ActionService(conversation_core=ScriptedModel(['```json\n{"action":"answer","content":"Readable answer."}\n```'])).run_action(
        goal="answer", messages=[], output_sink=sink)
    assert result["content"] == "Readable answer."
    assert published == ["Readable answer."]


@pytest.mark.parametrize("calls", [
    [{"action": "capability_inspect", "id": "same", "capability_names": ["read"]},
     {"tool_name": "read", "id": "same", "args": {}}],
    [{"action": "capability_inspect", "capability_names": ["read"]}, {"action": "answer", "content": "Done"}],
    [{"action": "capability_inspect", "capability_names": [" "]}],
    [{"action": "capability_inspect", "capability_names": ["read"], "procedure_refs": ["r@1"]}],
])
def test_invalid_mixed_batches_fail_as_a_whole(calls):
    with pytest.raises(InvalidModelAction):
        parse_model_action(json.dumps({"action": "tool_calls", "calls": calls}))


