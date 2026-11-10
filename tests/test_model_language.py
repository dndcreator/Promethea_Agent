import json
from types import SimpleNamespace

import pytest

from gateway.model_language import LANGUAGE_POLICY, response_language_context, with_response_language
from gateway.reasoning_service import ReasoningService


def test_original_request_and_ui_language_remain_data_not_system_instructions():
    context = response_language_context("Generated English objective", SimpleNamespace(input_payload={
        "message": "请核对这份报价", "metadata": {"ui_language": "zh"}}))
    original = [{"role": "system", "content": "Return canonical JSON; do not execute proposals."}]
    messages = with_response_language(original, context)
    assert messages[0]["content"] == LANGUAGE_POLICY
    assert original == [{"role": "system", "content": "Return canonical JSON; do not execute proposals."}]
    assert messages[-1]["role"] == "user"
    assert json.loads(messages[-1]["content"]) == {"original_request": "请核对这份报价", "ui_language": "zh"}
    repeated = with_response_language(messages, context)
    assert sum(row.get("name") == "promethea_response_language" for row in repeated) == 1
    assert sum(row["content"] == LANGUAGE_POLICY for row in repeated) == 1


@pytest.mark.asyncio
async def test_reasoning_calls_receive_language_context_without_extra_model_call():
    calls = []

    class Core:
        async def call_llm(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return {"content": '{"summary":"先检查文件"}'}

    service = ReasoningService(conversation_core=Core())
    context = response_language_context("请检查文件", {"input_payload": {"metadata": {"ui_language": "zh"}}})
    config = {"_runtime_call": {"response_language": context}}
    result = await service._call_json([{"role": "system", "content": "Return one JSON object."}], user_config=config, user_id="alice")
    assert result["summary"] == "先检查文件" and len(calls) == 1
    assert json.loads(calls[0][0][-1]["content"]) == context
    assert calls[0][1]["user_id"] == "alice"


@pytest.mark.asyncio
async def test_reasoning_run_propagates_language_without_mutating_shared_configuration(monkeypatch):
    service = ReasoningService(conversation_core=SimpleNamespace())
    seen = []

    async def gate(**kwargs):
        seen.append(kwargs["user_config"])
        return {"needs_reasoning": False}

    monkeypatch.setattr(service, "_gate_reasoning", gate)
    config = {"reasoning": {"enabled": True}, "_runtime_call": {"purpose": "action"}}
    await service.run(session_id="s", user_id="alice", user_message="English task wrapper", recent_messages=[],
                      base_system_prompt="Policy", user_config=config,
                      run_context={"input_payload": {"message": "核对报价", "metadata": {"ui_language": "zh"}}})
    assert seen[0]["_runtime_call"]["response_language"]["original_request"] == "核对报价"
    assert seen[0]["_runtime_call"]["purpose"] == "reasoning"
    assert config["_runtime_call"] == {"purpose": "action"}
