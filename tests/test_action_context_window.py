import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from gateway.action import ActionService
from gateway.action.context_window import CONTEXT_ANCHOR
from gateway.action.observation import RuntimeObservation
from gateway.conversation_service import ConversationService
from gateway.model_protocol import request_fields, response_fields
from memory.adapter import MemoryAdapter
from tests.support.runtime import ScriptedModel


@pytest.mark.asyncio
async def test_action_continues_across_context_windows_with_original_evidence_in_checkpoint():
    count = 7
    model = ScriptedModel([{"action": "tool_call", "tool_name": "fixture.inspect", "args": {"number": i}}
                           for i in range(count)] + [{"action": "answer", "content": "done"}])
    checkpoints = []
    actions = []

    def execute(_, args):
        actions.append(args["number"])
        return {"path": f"file-{args['number']}", "body": "x" * 3500}

    result = await ActionService(conversation_core=model).run_action(
        goal="inspect files", messages=[{"role": "system", "content": "Keep the safety policy"},
                                         {"role": "user", "content": "inspect files"}], budget=10,
        user_config={"action": {"context_action_batches": 3}}, tool_executor=execute,
        checkpoint_sink=checkpoints.append,
    )
    assert result["content"] == "done" and actions == list(range(count))
    assert len(checkpoints[-1]["observations"]) == count
    assert checkpoints[-1]["observations"][0]["structured_result"]["body"] == "x" * 3500
    assert any(row["event"] == "action.context_rebuilt" for row in result["action_trace"])
    assert all(call[0]["content"] == "Keep the safety policy" and call[1]["content"] == "inspect files" for call in model.calls)
    compacted = [call for call in model.calls if any(row.get("name") == CONTEXT_ANCHOR for row in call)]
    assert compacted and all(sum(row.get("_runtime_observation", False) for row in call) <= 3 for call in compacted)
    saved = next(row for row in checkpoints if row["step"] == 6 and not row["pending_calls"]
                 and any(message.get("name") == CONTEXT_ANCHOR for message in row["messages"]))
    actions.clear()
    restarted = ScriptedModel([{"action": "tool_call", "tool_name": "fixture.inspect", "args": {"number": 6}},
                               {"action": "answer", "content": "resumed"}])
    resumed = await ActionService(conversation_core=restarted).run_action(
        goal="inspect files", messages=[], checkpoint=saved,
        user_config={"action": {"context_action_batches": 3}}, tool_executor=execute,
    )
    assert resumed["content"] == "resumed" and actions == [6]


def test_compaction_preserves_native_pairs_and_user_guidance():
    from gateway.action.context_window import compact_action_history

    rows, evidence, wire = [], [], {}
    for i in range(4):
        step, call = f"step{i}", f"call{i}"
        packet = {"role": "assistant", "tool_calls": [{"id": call, "type": "function", "function": {
            "name": "tool_call", "arguments": '{"tool_name":"fixture.read","args":{}}',
        }}]}
        accepted = response_fields(packet)
        wire[step] = {"message": packet, "bindings": accepted["native_bindings"]}
        obs = RuntimeObservation(action_loop_id="loop", model_step_id=step, tool_call_id=call,
                                 tool_name="fixture.read", ok=True, structured_result={"path": f"file{i}"})
        evidence.append(obs.as_dict())
        rows.extend(ActionService._observation_messages(accepted["content"], [obs], model_step_id=step))
        if i == 0:
            rows.append({"role": "user", "content": "Do not overwrite files"})
    original = deepcopy(evidence)
    projected, changed = compact_action_history(rows, evidence, max_chars=4000, max_batches=3,
                                                 per_result_chars=1000, goal="inspect files")
    assert changed and evidence == original
    assert any(row["content"] == "Do not overwrite files" for row in projected)
    request = request_fields(projected, {"protocol": "native", "wire_history": wire, "observations": evidence})
    assert [row["tool_call_id"] for row in request["messages"] if row["role"] == "tool"] == ["call3"]
    assert evidence[0]["observation_id"] in str(request["messages"])


def test_l0_reconstruction_only_reads_unreplayed_owner_session(tmp_path):
    path = tmp_path / "l0.jsonl"
    rows = [{"entry_id": key, "user_id": user, "session_id": session, "role": "user", "content": key}
            for key, user, session in [("replayed", "alice", "one"), ("private", "bob", "one"),
                                       ("other-session", "alice", "two"), ("pending", "alice", "one")]]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with path.open(encoding="utf-8") as handle:
        handle.readline()
        offset = handle.tell()
    adapter = object.__new__(MemoryAdapter)
    adapter._raw_log_enabled, adapter._raw_log_path = True, path
    adapter._raw_log_state = {"last_offset": offset}
    assert adapter.pending_replay_context(user_id="alice", session_id="one") == [
        {"entry_id": "pending", "role": "user", "excerpt": "pending"},
    ]
    assert adapter._raw_log_state == {"last_offset": offset}


@pytest.mark.asyncio
async def test_reconstruction_uses_governed_deep_recall_and_preserves_l0_when_unavailable():
    from gateway.memory_service import MemoryService
    from gateway.memory_recall_schema import RecalledMemoryItem

    async def recall(request):
        assert (request.user_id, request.session_id, request.mode, request.top_k) == ("alice", "work", "deep", 4)
        assert request.query_text == "verify exports"
        return SimpleNamespace(memory_records=[
            RecalledMemoryItem(memory_id="concept", source_layer="concept", content="verify saved output", relevance_score=.8),
            RecalledMemoryItem(memory_id="recent", source_layer="recent", content="already visible", relevance_score=.9),
        ])

    def pending(**scope):
        assert scope == {"user_id": "alice", "session_id": "work"}
        return [{"entry_id": "raw1", "excerpt": "pending"}]

    service = SimpleNamespace(enabled=True, memory_adapter=SimpleNamespace(pending_replay_context=pending), recall_memory=recall)
    arguments = {"goal": "verify exports", "user_id": "alice", "session_id": "work"}
    result = await MemoryService.reconstruct_context(service, **arguments)
    assert [item["id"] for item in result["recalled_memory"]] == ["concept"]

    async def unavailable(_):
        raise OSError("offline store")

    service.recall_memory = unavailable
    fallback = await MemoryService.reconstruct_context(service, **arguments)
    assert fallback == {"recalled_memory": [], "l0_pending_replay": result["l0_pending_replay"]}


@pytest.mark.asyncio
async def test_conversation_rebuild_recalls_only_at_boundary_and_preserves_source_labels():
    calls = []

    async def recall(**kwargs):
        calls.append(kwargs)
        return {"recalled_memory": [{"id": "m1", "excerpt": "prior procedure"}],
                "l0_pending_replay": [{"entry_id": "raw1", "excerpt": "unconfirmed statement"}]}

    service = ConversationService(memory_service=SimpleNamespace(reconstruct_context=recall))
    context = SimpleNamespace(user_id="alice", session_id="work")
    row = {"role": "user", "name": CONTEXT_ANCHOR, "content": "evidence", "_runtime_rebuild": "verify exports"}
    prepared = await service._prepare_action_messages([row], [], run_context=context, user_config={})
    repeated = await service._prepare_action_messages(prepared, [], run_context=context, user_config={})
    assert repeated == prepared and calls == [{"goal": "verify exports", "user_id": "alice", "session_id": "work"}]
    assert "pending replay and do not certify facts" in prepared[-1]["content"]


@pytest.mark.asyncio
async def test_archived_observations_can_be_discovered_and_read_by_owner(tmp_path):
    from agentkit.tools.standard.runtime_tools import RuntimeListObservationsTool, RuntimeReadObservationTool
    from gateway.capability_service import ToolInvocationContext
    from gateway.protocol import EventType
    from gateway.runtime_event_log import RuntimeEventLog

    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    server = SimpleNamespace(event_emitter=SimpleNamespace(event_log=log))
    for key, owner, task in [("private", "bob", "t1"), ("wrong-task", "alice", "t2"),
                             ("first", "alice", "t1"), ("second", "alice", "t1")]:
        log.append(event_type=EventType.ACTION_OBSERVATION_COMMITTED.value, payload={
            "user_id": owner, "task_id": task, "session_id": "old-session", "observation_id": key,
            "tool_name": "fixture.read", "ok": True, "structured_result": {"content": key * 500},
        })
    ctx = ToolInvocationContext(user_id="alice", session_id="new-session", metadata={"run_context": SimpleNamespace(task_id="t1")})
    listing = RuntimeListObservationsTool(gateway_server=server)
    first = await listing.invoke({"limit": 1}, ctx)
    second = await listing.invoke({"limit": 1, "after_seq": first["next_after_seq"]}, ctx)
    assert [page["observations"][0]["observation_id"] for page in (first, second)] == ["first", "second"]
    assert second["next_after_seq"] is None
    read = RuntimeReadObservationTool(gateway_server=server)
    result = await read.invoke({"observation_id": "first", "max_chars": 5000}, ctx)
    assert json.loads(result["content"])["content"] == "first" * 500
    with pytest.raises(FileNotFoundError):
        await read.invoke({"observation_id": "private"}, ctx)
