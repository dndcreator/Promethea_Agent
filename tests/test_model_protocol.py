from copy import deepcopy
import json
import os
import shlex
import subprocess
import sys
from types import SimpleNamespace

import httpx
from openai import APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
import pytest

from agentkit.security.approval import approval_scope
from agentkit.security.sandbox import SandboxPolicy
from conversation_core import PrometheaConversation
from gateway.action import ActionService
from gateway.capability_service import CapabilityService, ToolInvocationContext
from gateway.events import EventEmitter
from gateway.model_protocol import NativeStream, decode_native, request_fields
from gateway.tool_prompt_blocks import build_action_protocol_prompt
from gateway.workspace_service import WorkspaceService


def packet(kind, args, identifier="native_one"):
    return {"role": "assistant", "content": None, "reasoning_content": "opaque provider reasoning",
            "tool_calls": [{"id": identifier, "type": "function", "function": {"name": kind, "arguments": json.dumps(args)}}]}


def core(monkeypatch, packets, *, stream=False):
    import conversation_core
    import gateway.user_secrets
    monkeypatch.setattr(gateway.user_secrets, "resolve_llm_runtime_settings", lambda *a, **k: {"tool_protocol": "native"})
    async def no_quote(*a):
        return None
    monkeypatch.setattr(conversation_core, "_model_quote", no_quote)
    instance = object.__new__(PrometheaConversation)
    instance._get_client_params = lambda *a, **k: ("fake", "https://example.invalid", "fixture", 0, 8192, [])
    requests, values = [], iter(packets)
    async def create(**params):
        requests.append(deepcopy(params))
        value = next(values)
        if isinstance(value, Exception):
            raise value
        if stream:
            async def chunks():
                for delta in value:
                    yield ChatCompletionChunk.model_validate({"id": "wire", "object": "chat.completion.chunk", "created": 0, "model": "fixture", "choices": [{"index": 0, **delta}]})
            return chunks()
        finish = value.pop("_finish", "tool_calls" if value.get("tool_calls") else "stop")
        return ChatCompletion.model_validate({"id": "wire", "object": "chat.completion", "created": 0, "model": "fixture", "choices": [{"index": 0, "message": value, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    instance._resolve_async_client = lambda *a: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return instance, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("admission_closed", [False, True])
async def test_provider_failure_after_committed_write(stream, admission_closed, monkeypatch, tmp_path):
    status = 403 if admission_closed else 503
    detail = {"code": "EVALUATION_ADMISSION_CLOSED"} if admission_closed else {}
    failure = APIStatusError("fixture failure", response=httpx.Response(
        status, request=httpx.Request("POST", "https://example.invalid"),
    ), body=detail)
    first = packet("tool_call", {"tool_name": "workspace.write_file", "args": {}}, "write")
    verify = packet("tool_call", {"tool_name": "computer_control.browser_action", "args": {"action": "preview", "path": "index.html"}}, "verify")
    final = {"role": "assistant", "content": "The file was saved and verified."}

    def wire(message):
        if not stream:
            return message
        calls = message.get("tool_calls")
        return [{"delta": {"tool_calls": [{"index": 0, **calls[0]}]} if calls else {"content": message["content"]},
                 "finish_reason": "tool_calls" if calls else "stop"}]

    conv, requests = core(monkeypatch, [wire(first), failure, wire(verify), wire(final)], stream=stream)
    executed, updates, checkpoints = [], [], []
    artifact = tmp_path / "index.html"

    def execute(name, _):
        executed.append(name)
        if name == "workspace.write_file":
            artifact.write_text("<title>Ready</title>", encoding="utf-8")
        else:
            assert artifact.read_text(encoding="utf-8") == "<title>Ready</title>"
        return {"path": artifact.name}

    async def publish(update):
        updates.append(update)

    result = await ActionService(conversation_core=conv).run_action(
        goal="Create and verify an HTML file", messages=[], budget=3,
        tool_executor=execute, output_sink=publish if stream else None,
        checkpoint_sink=checkpoints.append,
    )
    assert result["usage"]["usage_complete"] is False
    assert checkpoints[-1]["result"]["content"] == result["content"]
    assert artifact.exists()
    if admission_closed:
        assert executed == ["workspace.write_file"]
        assert len(requests) == 2
        assert result["execution_outcome"]["response_source"] == "runtime"
        assert result["execution_outcome"]["goal_status"] == "unverified"
        assert "paused" in result["content"] and artifact.name in result["content"]
    else:
        assert executed == ["workspace.write_file", "computer_control.browser_action"]
        assert len(requests) == 4
        assert requests[1] == requests[2]
        assert result["content"] == final["content"]
        assert any(row["event"] == "action.model_transport_retry" for row in result["action_trace"])
    if stream:
        assert updates[-1] == result["content"]


@pytest.mark.asyncio
async def test_runtime_owns_provider_retry_instead_of_sdk(monkeypatch):
    conv, _ = core(monkeypatch, [])
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(503, json={"error": {"message": "Unavailable"}})
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "created": 0, "model": "fixture",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Ready."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        })

    async with AsyncOpenAI(api_key="fixture", base_url="https://example.invalid/v1", max_retries=3,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))) as client:
        conv._resolve_async_client = lambda *_: client
        result = await ActionService(conversation_core=conv).run_action(goal="Reply", messages=[], budget=1)

    assert result["content"] == "Ready."
    assert len(requests) == 2 and requests[0] == requests[1]
    assert sum(row["event"] == "action.model_transport_retry" for row in result["action_trace"]) == 1
    assert result["usage"]["usage_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["code.run_python", "runtime.exec_command"])
async def test_native_model_receives_bounded_process_failure_diagnostic(monkeypatch, tmp_path, name):
    monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy(enabled=False))
    workspace = WorkspaceService(base_dir=str(tmp_path / "workspaces"))
    capability = CapabilityService(event_emitter=EventEmitter())
    capability.bind_tool_runtime(workspace_service=workspace)
    capability.ensure_discovered_tools()
    ctx = ToolInvocationContext(user_id="alice", session_id="session")
    script = (
        "import sys\nprint('not-for-model')\n"
        "print('diagnostic-prefix-' * 100, file=sys.stderr)\n"
        "import promethea_nonexistent_fixture_dependency\n"
    )
    if name == "code.run_python":
        args = {"code": script}
    else:
        await capability.call_tool("workspace.write_file", {"path": "failure.py", "content": script}, ctx=ctx)
        argv = [sys.executable, "failure.py"]
        args = {"command": subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)}
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": name, "args": args}),
                                       {"role": "assistant", "content": "The dependency is unavailable."}])

    async def execute(tool_name, params):
        with approval_scope(tool_name, params, confirmed=True):
            return await capability.call_tool(tool_name, params, ctx=ctx)

    await ActionService(conversation_core=conv).run_action(
        goal="Check the dependency", messages=[{"role": "system", "content": build_action_protocol_prompt()}],
        user_id="alice", session_id="session", tool_executor=execute,
    )
    receipt = next(row for row in requests[1]["messages"] if row["role"] == "tool")
    observation, = json.loads(receipt["content"])["observations"]
    assert observation["status"] == "failed" and observation["result"] is None
    error = observation["error"]
    assert error["code"] == "PROCESS_EXIT_NONZERO" and not error["retryable"]
    assert error["details"]["returncode"] != 0 and error["details"]["stderr_tail_truncated"]
    tail = error["details"]["stderr_tail"]
    assert len(tail) <= 512 and "ModuleNotFoundError: No module named 'promethea_nonexistent_fixture_dependency'" in tail
    assert "not-for-model" not in receipt["content"]


@pytest.mark.asyncio
async def test_native_recovery_denial_replays_receipts_without_dispatch(monkeypatch):
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.read", "args": {}}, "first"),
        packet("tool_calls", {"calls": [{"id": "again", "tool_name": "fixture.read", "args": {}},
                                       {"id": "send", "tool_name": "fixture.send", "args": {}}]}, "blocked_batch"),
        packet("await_user", {"content": "Please restore the resource"}, "wait")])
    executed = []

    def execute(name, args):
        executed.append(name)
        return {"ok": False, "error_detail": {"code": "RESOURCE_CLOSED", "retryable": False, "message": "closed"}}

    out = await ActionService(conversation_core=conv).run_action(goal="deliver", messages=[
        {"role": "system", "content": build_action_protocol_prompt()}], budget=5, tool_executor=execute)
    assert out["status"] == "needs_input" and executed == ["fixture.read"]
    reply = next(row for row in requests[-1]["messages"] if row.get("tool_call_id") == "blocked_batch")
    facts = json.loads(reply["content"])["observations"]
    assert len(facts) == 2 and all(row["error"]["code"] == "ACTION_REASSESSMENT_REQUIRED" for row in facts)


@pytest.mark.asyncio
@pytest.mark.parametrize("decline", [False, True])
async def test_native_approval_restart_keeps_ids_reasoning_and_runtime_truth(monkeypatch, decline):
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.send", "args": {"text": "hello"}}),
                                       {"role": "assistant", "content": "Finished without inventing a result."}])
    calls = []
    pending = await ActionService(conversation_core=conv).run_action(goal="send", messages=[{"role": "system", "content": build_action_protocol_prompt()}, {"role": "user", "content": "send"}],
        confirmation_resolver=lambda *a: True, tool_executor=lambda *a: calls.append(a), user_id="alice", session_id="session")
    assert pending["status"] == "needs_confirmation" and calls == []
    pending = json.loads(json.dumps(pending))
    assert pending["model_wire"] and pending["model_protocol"] == "native"
    service = ActionService(conversation_core=conv)
    options = dict(pending=pending, user_config=None, user_id="alice", session_id="session", run_context=None,
                   confirmation_resolver=lambda *a: True, tool_executor=lambda *a: calls.append(a) or {"sent": True})
    result = await service.reject_pending_action(**options) if decline else await service.resume_action(**options, approved_call_id="native_one")
    assert result["status"] == "success", result
    assert len(calls) == (0 if decline else 1)
    native = next(row for row in requests[-1]["messages"] if row.get("tool_calls"))
    receipt = next(row for row in requests[-1]["messages"] if row["role"] == "tool")
    assert native["reasoning_content"] == "opaque provider reasoning"
    assert receipt["tool_call_id"] == native["tool_calls"][0]["id"] == "native_one"
    assert ("USER_DECLINED" in receipt["content"]) == decline
    assert "Return exactly one JSON" not in requests[0]["messages"][0]["content"]
    assert {row["function"]["name"] for row in requests[0]["tools"]} == {"answer", "tool_call", "tool_calls", "capability_inspect", "capability_request", "await_user"}


@pytest.mark.asyncio
async def test_native_wait_restart_replays_a_user_report_not_an_approval(monkeypatch):
    conv, requests = core(monkeypatch, [packet("await_user", {"content": "Please verify the page"}, "human_step"),
                                      {"role": "assistant", "content": "I will inspect the page again."}])
    saved = []
    result = await ActionService(conversation_core=conv).run_action(goal="verify", messages=[{"role": "system", "content": build_action_protocol_prompt()}, {"role": "user", "content": "verify"}],
        user_id="alice", session_id="session", checkpoint_sink=lambda value: saved.append(json.loads(json.dumps(value))))
    assert result["status"] == "needs_input" and len(requests) == 1
    pending = saved[-1]
    resumed = await ActionService(conversation_core=conv).run_action(goal="verify", messages=[], user_id="alice", session_id="session",
        checkpoint={**pending, "input_response": {"request_id": result["input_request"]["request_id"], "content": "Done"}})
    assert resumed["status"] == "success" and len(requests) == 2
    fact = next(row for row in requests[-1]["messages"] if row.get("role") == "tool")
    assert fact["tool_call_id"] == "human_step"
    report = json.loads(fact["content"])["observations"][0]["result"]
    assert report["user_report"] == "Done" and report["external_result_verified"] is False
    assert report["tool_authorization_granted"] is False


@pytest.mark.asyncio
async def test_budget_completion_keeps_schemas_stable_but_rejects_executable_native_actions(monkeypatch):
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.read", "args": {}}, "read"),
        packet("await_user", {"content": "Please verify the page"}, "boundary_wait"),
        {"role": "assistant", "content": "I will inspect the reported change."}])
    saved, effects = [], []
    first = await ActionService(conversation_core=conv).run_action(goal="verify", messages=[{"role": "system", "content": build_action_protocol_prompt()}],
        user_id="alice", session_id="s", budget=1, tool_executor=lambda *args: effects.append(args) or {"read": True},
        checkpoint_sink=lambda value: saved.append(deepcopy(value)))
    assert first["status"] == "needs_input" and len(effects) == 1
    assert requests[1]["tools"] == requests[0]["tools"]
    with pytest.raises(ValueError):
        decode_native(packet("tool_call", {"tool_name": "fixture.write", "args": {}}), final=True)
    resumed = await ActionService(conversation_core=conv).run_action(goal="verify", messages=[], user_id="alice", session_id="s", budget=1,
        checkpoint={**saved[-1], "input_response": {"request_id": first["input_request"]["request_id"], "content": "Done"}})
    assert resumed["status"] == "success" and len(effects) == 1


@pytest.mark.asyncio
async def test_independent_native_inspection_resolution_and_tool_share_one_step(monkeypatch):
    proposals = [packet("capability_inspect", {"capability_names": ["fixture.read"]}, "inspect"),
                 packet("capability_request", {"objective": "read", "required_capabilities": ["fixture"]}, "resolve"),
                 packet("tool_call", {"tool_name": "fixture.read", "args": {}}, "read")]
    mixed = {"role": "assistant", "content": None, "tool_calls": [row["tool_calls"][0] for row in proposals]}
    conv, requests = core(monkeypatch, [mixed, {"role": "assistant", "content": "Done"}])
    seen = []
    async def inspect(names):
        seen.append(("inspect", names))
        return {"schema": "actual"}
    async def resolve(intent):
        seen.append(("resolve", intent))
        return {"candidates": [{"name": "fixture.read"}], "process_experience": {"rules": [{"reference": "r@1"}]}}
    out = await ActionService(conversation_core=conv).run_action(goal="read", messages=[], budget=2,
        capability_inspector=inspect, capability_resolver=resolve,
        tool_executor=lambda name, args: seen.append((name, args)) or {"value": 29})
    assert out["status"] == "success" and len(seen) == 3 and len(requests) == 2
    replies = [row for row in requests[-1]["messages"] if row["role"] == "tool"]
    assert [row["tool_call_id"] for row in replies] == ["inspect", "resolve", "read"]
    assert [json.loads(row["content"])["observations"][0]["subject"] for row in replies] == [
        "runtime.capability_inspect", "runtime.capability_resolve", "fixture.read"]
    assert out["execution_path"][1]["exposed_procedures"] == ["r@1"]
    assert all(row["ok"] for row in out["observations"])


@pytest.mark.asyncio
@pytest.mark.parametrize("decline", [False, True])
async def test_mixed_native_batch_approval_restart_keeps_query_identity(monkeypatch, decline):
    mixed = packet("capability_inspect", {"capability_names": ["fixture.send"]}, "inspect")
    mixed["tool_calls"] += packet("tool_call", {"tool_name": "fixture.send", "args": {}}, "send")["tool_calls"]
    conv, requests = core(monkeypatch, [mixed, {"role": "assistant", "content": "Done"}])
    seen = []
    async def inspect(names):
        seen.append("inspect")
        return {"names": names}
    options = dict(tool_executor=lambda *args: seen.append("send") or {"sent": True}, capability_inspector=inspect,
                   confirmation_resolver=lambda *args: True, user_id="alice", session_id="s", user_config=None, run_context=None)
    pending = await ActionService(conversation_core=conv).run_action(goal="send", messages=[], **options)
    assert pending["status"] == "needs_confirmation" and not seen
    pending = json.loads(json.dumps(pending))
    service = ActionService(conversation_core=conv)
    out = await service.reject_pending_action(pending=pending, **options) if decline else await service.resume_action(
        pending=pending, approved_call_id="send", **options)
    assert out["status"] == "success" and seen == ([] if decline else ["inspect", "send"])
    replies = [row for row in requests[-1]["messages"] if row["role"] == "tool"]
    assert [row["tool_call_id"] for row in replies] == ["inspect", "send"]
    assert all(len(json.loads(row["content"])["observations"]) == 1 for row in replies)


@pytest.mark.asyncio
async def test_named_internal_tool_cannot_impersonate_a_capability_operation(monkeypatch):
    conv, _ = core(monkeypatch, [packet("tool_call", {"tool_name": "runtime.capability_inspect", "args": {}}, "spoof")])
    seen = []
    out = await ActionService(conversation_core=conv).run_action(goal="inspect", messages=[],
        confirmation_resolver=lambda *args: True, capability_inspector=lambda *args: seen.append("inspect"),
        tool_executor=lambda *args: seen.append("tool"))
    assert out["status"] == "needs_confirmation" and not seen


@pytest.mark.asyncio
async def test_final_native_tool_proposal_is_rejected_even_with_stable_definitions(monkeypatch):
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.read", "args": {}}, "read"),
        packet("tool_call", {"tool_name": "fixture.send", "args": {}}, "must_not_run")])
    seen = []
    out = await ActionService(conversation_core=conv).run_action(goal="read", messages=[], budget=1,
        tool_executor=lambda name, args: seen.append(name) or {"read": True})
    assert seen == ["fixture.read"] and len(requests) == 2
    assert requests[0]["tools"] == requests[1]["tools"]
    assert out["execution_outcome"]["goal_status"] == "unverified"
    assert out["completion_error"] and any(row["tool_name"] == "runtime.completion" and not row["ok"] for row in out["observations"])


@pytest.mark.asyncio
async def test_accepted_observation_projection_survives_next_call_and_checkpoint(monkeypatch):
    from gateway.runtime_io import ContextCompiler
    conv, requests = core(monkeypatch, [packet("tool_call", {"tool_name": "fixture.read", "args": {}}, "large"),
        packet("tool_call", {"tool_name": "fixture.stat", "args": {}}, "small"), {"role": "assistant", "content": "Done"}])
    checkpoints = []
    async def prepare(messages, observations):
        return ContextCompiler.project_observations(messages, observations, per_result_chars=4000, total_chars=8000)
    out = await ActionService(conversation_core=conv).run_action(goal="read", messages=[], budget=3,
        tool_executor=lambda name, args: {"body": "x" * 20000} if name.endswith("read") else {"count": 29},
        prepare_messages=prepare, checkpoint_sink=lambda value: checkpoints.append(deepcopy(value)))
    assert out["status"] == "success"
    before = next(row for row in requests[1]["messages"] if row.get("tool_call_id") == "large")
    after = next(row for row in requests[2]["messages"] if row.get("tool_call_id") == "large")
    assert before == after
    projected = json.loads(before["content"])["observations"][0]
    assert projected["result"]["truncated"]
    assert out["observations"][0]["structured_result"]["body"] == "x" * 20000
    assert any(projected["result"]["content_hash"] in json.dumps(row["messages"]) for row in checkpoints)


@pytest.mark.asyncio
async def test_native_capability_observation_and_batch_use_existing_runtime(monkeypatch):
    conv, requests = core(monkeypatch, [packet("capability_inspect", {"capability_names": ["fixture.read"]}, "inspect"),
        {**packet("tool_call", {"tool_name": "fixture.read", "args": {"n": 1}}, "one"), "tool_calls": [
            packet("tool_call", {"tool_name": "fixture.read", "args": {"n": 1}}, "one")["tool_calls"][0],
            packet("tool_call", {"tool_name": "fixture.read", "args": {"n": 2}}, "two")["tool_calls"][0]]},
        {"role": "assistant", "content": "Done"}])
    async def inspect(names):
        return {"names": names}
    seen = []
    result = await ActionService(conversation_core=conv).run_action(goal="read", messages=[], capability_inspector=inspect,
        tool_executor=lambda name, args: seen.append(args["n"]) or {"n": args["n"]}, budget=4)
    assert result["status"] == "success" and sorted(seen) == [1, 2]
    assert len([row for row in requests[-1]["messages"] if row["role"] == "tool"]) == 3


@pytest.mark.asyncio
async def test_native_truncation_never_dispatches_and_recovery_is_bounded(monkeypatch):
    conv, requests = core(monkeypatch, [{**packet("tool_call", {"tool_name": "fixture.send", "args": {}}), "_finish": "length"}, {"role": "assistant", "content": "Could not finish"}])
    calls = []
    result = await ActionService(conversation_core=conv).run_action(goal="send", messages=[], tool_executor=lambda *a: calls.append(a))
    assert result["status"] == "success" and not calls
    assert result["observations"][0]["error"]["code"] == "MODEL_OUTPUT_LIMIT"
    assert not any(row.get("tool_calls") for row in requests[1]["messages"])


@pytest.mark.asyncio
async def test_native_stream_assembles_arguments_before_dispatch(monkeypatch):
    call = packet("tool_call", {"tool_name": "fixture.read", "args": {}})["tool_calls"][0]
    args = call["function"]["arguments"]
    conv, requests = core(monkeypatch, [
        [{"delta": {"reasoning_content": "reason"}, "finish_reason": None},
         {"delta": {"tool_calls": [{"index": 0, "id": "native_one", "type": "function", "function": {"name": "tool_call", "arguments": args[:15]}}]}, "finish_reason": None},
         {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[15:]}}]}, "finish_reason": "tool_calls"}],
        [{"delta": {"content": "All done"}, "finish_reason": "stop"}]], stream=True)
    calls, output = [], []
    async def sink(text):
        output.append(text)
    result = await ActionService(conversation_core=conv).run_action(goal="read", messages=[], output_sink=sink, tool_executor=lambda *a: calls.append(a) or {"ok": True})
    assert result["status"] == "success" and len(calls) == 1
    assert result["content"] == "All done"
    assert next(row for row in requests[1]["messages"] if row.get("tool_calls"))["reasoning_content"] == "reason"


def test_projection_survives_compaction_and_cannot_borrow_receipts():
    message = packet("tool_call", {"tool_name": "read", "args": {}})
    message["annotations"] = [{"provider_output_only": True}]
    action, bindings = decode_native(message)
    runtime = {"protocol": "native", "purpose": "action", "wire_history": {"s": {"message": message, "bindings": bindings}},
               "observations": [{"observation_id": "obs", "tool_call_id": "native_one", "model_step_id": "s"}]}
    messages = [{"role": "system", "content": "Compacted summary"}, {"role": "assistant", "content": json.dumps(action), "_model_step_id": "s"},
        {"role": "user", "content": [{"type": "text", "text": json.dumps({"observation_id": "obs", "status": "completed"})}, {"type": "image_url", "image_url": {"url": "https://example.invalid/image"}}]}]
    projected = request_fields(messages, runtime)
    assert projected["messages"][0]["content"] == "Compacted summary"
    assert "annotations" not in projected["messages"][1] and "annotations" in message
    assert projected["messages"][-1]["content"][0]["type"] == "image_url"
    assert not any("_model_step_id" in row for row in projected["messages"])
    runtime["observations"][0]["tool_call_id"] = "another"
    with pytest.raises(ValueError, match="matching committed"):
        request_fields(messages, runtime)
    assert request_fields(messages, {"protocol": "prompt_json"})["messages"][1].get("_model_step_id") is None


def test_native_stream_parallel_indices_and_duplicate_ids_are_validated():
    stream = NativeStream()
    delta = ChatCompletionChunk.model_validate({"id": "r", "object": "chat.completion.chunk", "created": 0, "model": "fixture", "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": n, "id": "duplicate", "type": "function", "function": {"name": "tool_call", "arguments": '{"tool_name":"read","args":{}}'}} for n in [1, 0]]}}]})
    stream.feed(delta.choices[0].delta)
    with pytest.raises(ValueError, match="unique"):
        decode_native(stream.message())


def test_codec_never_rewrites_user_quotes_or_invents_provider_reasoning():
    prompt = build_action_protocol_prompt()
    fields = request_fields([{"role": "system", "content": prompt}, {"role": "user", "content": prompt}], {"protocol": "native", "purpose": "action"})
    assert fields["messages"][0]["content"] != prompt
    assert fields["messages"][1]["content"] == prompt
    stream = NativeStream()
    stream.feed(SimpleNamespace(content="hello"))
    assert "reasoning_content" not in stream.message()
    stream.feed(SimpleNamespace(content=None, reasoning_content="provider"))
    assert stream.message()["reasoning_content"] == "provider"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_invalid_native_history_is_local_failure_not_a_paid_provider_attempt(monkeypatch, stream):
    conv, requests = core(monkeypatch, [], stream=stream)
    messages = [{"role": "assistant", "content": "{}", "_model_step_id": "lost"}]
    settings = {"_runtime_call": {"purpose": "action", "protocol": "native"}}
    if stream:
        results = []
        async def receive(row):
            results.append(row)
        chunks = [row async for row in conv.call_llm_stream(messages, user_config=settings, result_sink=receive)]
        result = results[-1]
        assert chunks == ["[error] MODEL_PROTOCOL_HISTORY"]
    else:
        result = await conv.call_llm(messages, user_config=settings)
    assert not requests and result["code"] == "MODEL_PROTOCOL_HISTORY"
    assert result["request_sent"] is False and result["model_attempts"] == 0
    assert result["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed", [False, True])
async def test_native_checkpoint_restart_does_not_replay_unknown_side_effect(monkeypatch, mixed):
    proposal = packet("tool_call", {"tool_name": "fixture.send", "args": {}})
    if mixed:
        proposal["tool_calls"].insert(0, packet("capability_inspect", {"capability_names": ["fixture.send"]}, "inspect")["tool_calls"][0])
    conv, requests = core(monkeypatch, [proposal,
                                       {"role": "assistant", "content": "The previous outcome is unknown."}])
    saved, dispatched = [], []
    inspected = []
    async def inspect(names):
        inspected.extend(names)
        return {"names": names}
    class ProcessDeath(BaseException):
        pass
    async def crash(name, args):
        dispatched.append(name)
        raise ProcessDeath("simulated process death")
    with pytest.raises(ProcessDeath):
        await ActionService(conversation_core=conv).run_action(goal="send", messages=[], checkpoint_sink=lambda value: saved.append(deepcopy(value)), tool_executor=crash, capability_inspector=inspect)
    pending = next(row for row in reversed(saved) if row["pending_calls"])
    assert pending["model_protocol"] == "native" and pending["model_wire"]
    result = await ActionService(conversation_core=conv).run_action(goal="send", messages=[], checkpoint=json.loads(json.dumps(pending)), tool_executor=lambda *a: dispatched.append("replayed"), capability_inspector=inspect)
    assert dispatched == ["fixture.send"] and result["status"] == "success"
    assert inspected == (["fixture.send"] if mixed else [])
    assert any(row.get("error", {}).get("code") == "TOOL_OUTCOME_UNKNOWN" for row in result["observations"])


@pytest.mark.asyncio
async def test_combined_experiment_never_resets_or_bypasses_admission(tmp_path, monkeypatch):
    import openai
    from config import config
    from scripts.evaluate_native_budget import run
    async def forbidden(**kwargs):
        raise AssertionError("budget cannot admit a paid request")
    async def close():
        pass
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=forbidden)), close=close))
    env = tmp_path / ".env.eval"
    env.write_text("\n".join(["PROMETHEA_EVAL_AGENT_BASE_URL=https://example.invalid", "PROMETHEA_EVAL_AGENT_API_KEY=fake", "PROMETHEA_EVAL_AGENT_MODEL=fixture", "PROMETHEA_EVAL_AGENT_INPUT_USD_PER_MILLION=0.3", "PROMETHEA_EVAL_AGENT_OUTPUT_USD_PER_MILLION=1.2", "PROMETHEA_EVAL_MAX_COST_USD=0.75"]), encoding="utf-8")
    original = config.api.tool_protocol
    result = await run(tmp_path / "result", env, 0.000000001)
    assert result["total_calls"] == 0 and result["known_cost_usd"] == 0
    assert result["budget_report"] is None and result["stop_reason"]
    assert config.api.tool_protocol == original
