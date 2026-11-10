"""Deterministic lifecycle regressions, not live-model business acceptance."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from gateway.action import ActionService
from gateway.action.model_action import InvalidModelAction, parse_model_action
from gateway.action.state_machine import ActionPhase, RuntimeActionStateMachine, InvalidActionTransition
from gateway.model_protocol import decode_native
from tests.test_action_service import _Core
from tests.support.runtime import runtime_at, ScriptedModel


@pytest.mark.asyncio
async def test_wait_is_nonterminal_persistent_and_resumes_with_unverified_report():
    saved = []
    core = _Core([{"content": json.dumps({"action": "await_user", "content": "请完成页面验证"})}])
    first = await ActionService(conversation_core=core).run_action(
        goal="register", messages=[{"role": "user", "content": "register"}], user_id="alice", session_id="s",
        checkpoint_sink=lambda value: saved.append(deepcopy(value)), budget=1,
    )
    assert first["status"] == "needs_input"
    assert first["content"] == "请完成页面验证"
    assert first["action_state"]["phase"] == "waiting_input"
    assert not first["action_state"]["terminal"]
    assert len(core.calls) == 1
    waiting = saved[-1]
    idle = await ActionService(conversation_core=_Core([])).run_action(
        goal="register", messages=[], user_id="alice", session_id="s", checkpoint=waiting,
    )
    assert idle == first
    seen = []

    def inspect(messages):
        seen.extend(messages)
        return {"content": '{"action":"answer","content":"需要重新检查网页"}'}

    core2 = _Core([inspect])
    resumed = await ActionService(conversation_core=core2).run_action(
        goal="register", messages=[], user_id="alice", session_id="s", budget=1,
        checkpoint={**waiting, "input_response": {"request_id": first["input_request"]["request_id"], "content": "完成了"}},
    )
    assert resumed["status"] == "success"
    receipt = next(row for row in resumed["observations"] if row["tool_name"] == "runtime.user_input")
    assert receipt["structured_result"]["user_report"] == "完成了"
    assert receipt["structured_result"]["external_result_verified"] is False
    assert receipt["structured_result"]["tool_authorization_granted"] is False
    assert len(core2.calls) == 1 and seen
    with pytest.raises(PermissionError):
        await ActionService(conversation_core=_Core([])).run_action(goal="register", messages=[], user_id="bob", session_id="s", checkpoint=waiting)
    with pytest.raises(ValueError):
        await ActionService(conversation_core=_Core([])).run_action(goal="register", messages=[], user_id="alice", session_id="s", checkpoint={**waiting, "input_response": {"request_id": "stale", "content": "done"}})


def test_wait_request_protocol_is_bounded_and_native_batches_cannot_mix_it():
    action, _ = decode_native({"role": "assistant", "tool_calls": [{"id": "wait1", "type": "function", "function": {
        "name": "await_user", "arguments": '{"content":"请处理验证"}'}}]})
    assert action["action"] == "await_user"
    for value in ("", "x" * 4001, None):
        with pytest.raises(InvalidModelAction):
            parse_model_action(json.dumps({"action": "await_user", "content": value}))
    with pytest.raises(InvalidModelAction):
        parse_model_action('{"action":"await_user","content":"密码","input_kind":"secret"}')
    machine = RuntimeActionStateMachine()
    for phase in (ActionPhase.AWAITING_MODEL, ActionPhase.EVALUATING, ActionPhase.WAITING_INPUT):
        machine.transition(phase, cause="test")
    with pytest.raises(InvalidActionTransition):
        machine.transition(ActionPhase.EXECUTING, cause="user reply is not approval")


@pytest.mark.asyncio
async def test_session_wait_survives_restart_and_rejects_stale_reply(tmp_path):
    host = runtime_at(tmp_path, ScriptedModel([{"action": "await_user", "content": "请完成页面验证"}]))
    host.message_manager.create_session("s", "alice")
    first = await host.conversation_service.run_chat_loop([{"role": "user", "content": "start"}],
        user_id="alice", session_id="s")
    pending = host.message_manager.get_action_checkpoint("s", user_id="alice")
    assert pending["result"]["status"] == "needs_input"
    from gateway.public_views import public_pending_input
    assert set(public_pending_input(pending)) == {"request_id", "content", "input_kind"}
    assert host.message_manager.get_action_checkpoint("s", user_id="bob") is None
    model = ScriptedModel([{"action": "answer", "content": "我会重新检查页面"}])
    restored = runtime_at(tmp_path, model)
    with pytest.raises(ValueError, match="reply_to_input"):
        await restored.conversation_service.run_chat_loop([{"role": "user", "content": "完成了"}], user_id="alice", session_id="s",
            run_context=SimpleNamespace(user_id="alice", session_id="s", input_payload={"reply_to_input": "stale"}))
    assert not model.calls
    out = await restored.conversation_service.run_chat_loop([{"role": "user", "content": "完成了"}], user_id="alice", session_id="s",
        run_context=SimpleNamespace(user_id="alice", session_id="s", input_payload={"reply_to_input": first["input_request"]["request_id"]}))
    assert out["status"] == "success"
    assert restored.message_manager.get_action_checkpoint("s", user_id="alice") is None


@pytest.mark.asyncio
async def test_input_request_is_not_published_if_durable_save_fails():
    core = _Core([{"content": '{"action":"await_user","content":"请操作页面"}'}])
    published = []

    def fail(_):
        if _.get("pending_input"):
            raise OSError("disk full")

    async def publish(value):
        published.append(value)

    with pytest.raises(OSError, match="disk full"):
        await ActionService(conversation_core=core).run_action(goal="test", messages=[], checkpoint_sink=fail, output_sink=publish)
    assert not any(item.get("content") for item in published)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["acknowledgement", "text"])
async def test_background_task_wait_survives_runtime_restart_without_model_polling(tmp_path, kind):
    from tests.test_background_agents import host, start, drain
    model = ScriptedModel([{"action": "await_user", "content": "请提供说明", "input_kind": kind}])
    tasks, runtime, conversation, background = host(tmp_path, model)
    accepted = await start(conversation, background, tools=[])
    try:
        await drain(runtime)
        task = tasks.get_task(accepted["child_id"], user_id="alice")
        assert task["runs"][0]["status"] == "waiting_user"
        request = task["runs"][0]["metadata"]["checkpoint"]["pending_input"]
        await drain(runtime)
        assert len(model.calls) == 1
    finally:
        await runtime.shutdown()
    core = ScriptedModel([{"action": "answer", "content": "已收到说明"}])
    tasks2, runtime2, _, _ = host(tmp_path, core)
    try:
        await runtime2.recover_incomplete()
        await drain(runtime2)
        assert not core.calls
        with pytest.raises(ValueError):
            runtime2.resume_task(task_id=task["task_id"], user_id="alice")
        runtime2.resume_task(task_id=task["task_id"], user_id="alice", input_reply={"request_id": request["request_id"], "content": "这是测试输入"})
        await drain(runtime2)
        assert tasks2.get_task(task["task_id"], user_id="alice")["runs"][0]["status"] == "completed"
        assert len(core.calls) == 1
    finally:
        await runtime2.shutdown()
