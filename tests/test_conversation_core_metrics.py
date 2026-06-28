from __future__ import annotations

from types import SimpleNamespace

import pytest

import conversation_core
from conversation_core import PrometheaConversation


class _FakeCreate:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _conversation_with_client(client):
    conv = object.__new__(PrometheaConversation)
    conv._get_client_params = lambda user_config=None, user_id=None: (
        "key",
        "https://example.test/v1",
        "model-a",
        0.2,
        200,
        [],
    )
    conv._resolve_model_candidates = lambda user_config, model, failover_models=None: [model]
    conv._resolve_async_client = lambda user_config, api_key, base_url: client
    return conv


@pytest.mark.asyncio
async def test_call_llm_records_usage_metrics(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
    )
    create = _FakeCreate(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=create))
    conv = _conversation_with_client(client)
    recorded = []
    monkeypatch.setattr(conversation_core, "_record_llm_metrics", lambda duration, usage: recorded.append(usage))

    out = await conv.call_llm([{"role": "user", "content": "hi"}])

    assert out["usage"] == {"prompt_tokens": 12, "completion_tokens": 5}
    assert recorded == [{"prompt_tokens": 12, "completion_tokens": 5}]


@pytest.mark.asyncio
async def test_call_llm_stream_requests_and_records_stream_usage(monkeypatch):
    async def stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=7),
        )

    create = _FakeCreate(stream())
    client = SimpleNamespace(chat=SimpleNamespace(completions=create))
    conv = _conversation_with_client(client)
    recorded = []
    monkeypatch.setattr(conversation_core, "_record_llm_metrics", lambda duration, usage: recorded.append(usage))

    chunks = []
    async for chunk in conv.call_llm_stream([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    assert "".join(chunks) == "hello"
    assert create.calls[0]["stream_options"] == {"include_usage": True}
    assert recorded == [{"prompt_tokens": 20, "completion_tokens": 7}]
