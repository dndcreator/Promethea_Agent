import asyncio

import pytest

from gateway.cognitive_reducer import CognitiveRecallPolicy, CognitiveReducer


def _items(count: int):
    return [
        {
            "cognition_id": f"memory:{index}",
            "content": f"memory item {index}",
            "state": "current",
            "importance": 0.5,
            "relevance_score": 0.5,
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_fast_reducer_never_calls_llm():
    calls = 0

    async def llm_call(_messages):
        nonlocal calls
        calls += 1
        return {"status": "success", "content": "{}"}

    result = await CognitiveReducer(llm_call=llm_call).reduce(
        query="query",
        items=_items(2),
        policy=CognitiveRecallPolicy(),
        requested_mode="auto",
    )

    assert result["mode"] == "fast"
    assert result["metrics"]["llm_calls"] == 0
    assert calls == 0


@pytest.mark.asyncio
async def test_adaptive_reducer_degrades_on_deadline():
    async def slow_llm(_messages):
        await asyncio.sleep(0.2)
        return {"status": "success", "content": "{}"}

    result = await CognitiveReducer(llm_call=slow_llm).reduce(
        query="query",
        items=_items(20),
        policy=CognitiveRecallPolicy(deadline_ms=20),
        requested_mode="adaptive",
    )

    assert result["mode"] == "adaptive"
    assert result["metrics"]["degraded"] is True
    assert result["metrics"]["degraded_reason"] == "deadline_exceeded"
    assert result["synthesis"]
