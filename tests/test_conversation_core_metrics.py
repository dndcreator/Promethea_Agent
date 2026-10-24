from __future__ import annotations

from types import SimpleNamespace

import pytest

import conversation_core
from conversation_core import PrometheaConversation
from conversation_core import _loggable_message_content


class _FakeCreate:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _UnsupportedImageError(Exception):
    status_code = 400
    body = {"error": {"code": "unsupported_value", "message": "model does not support image input"}}


class _FailingCreate:
    def __init__(self, error):
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


class _SequenceCreate:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_multimodal_log_summary_omits_binary_payloads():
    logged = _loggable_message_content([
        {"type": "text", "text": "Describe this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,secret-bytes"}},
    ])

    assert "Describe this" in logged
    assert "[image input omitted]" in logged
    assert "secret-bytes" not in logged


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
    monkeypatch.setattr(conversation_core, "_record_llm_metrics", lambda duration, usage, **kwargs: recorded.append(usage))

    out = await conv.call_llm([{"role": "user", "content": "hi"}])

    assert out["usage"] == {"prompt_tokens": 12, "completion_tokens": 5}
    assert recorded == [{"prompt_tokens": 12, "completion_tokens": 5}]


@pytest.mark.asyncio
@pytest.mark.parametrize("content,finish_reason,code", [
    ("", "stop", "MODEL_EMPTY_RESPONSE"),
    ("   ", "stop", "MODEL_EMPTY_RESPONSE"),
    ("partial action", "length", "MODEL_OUTPUT_LIMIT"),
])
async def test_non_stream_model_output_errors_preserve_terminal_facts(content, finish_reason, code):
    response = SimpleNamespace(
        id="provider-sync", choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
    )
    create = _FakeCreate(response)
    conv = _conversation_with_client(SimpleNamespace(chat=SimpleNamespace(completions=create)))
    out = await conv.call_llm([{"role": "user", "content": "build"}])
    assert out["status"] == "error" and out["code"] == code
    assert out["finish_reason"] == finish_reason and out["request_id"] == "provider-sync"
    assert out["max_tokens"] == 200 and out["usage"]["completion_tokens"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("content,finish_reason,code", [
    ("", "stop", "MODEL_EMPTY_RESPONSE"),
    ("   ", "stop", "MODEL_EMPTY_RESPONSE"),
    ("partial action", "length", "MODEL_OUTPUT_LIMIT"),
])
async def test_non_stream_model_output_errors_preserve_terminal_facts(content, finish_reason, code):
    response = SimpleNamespace(
        id="provider-sync", choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
    )
    create = _FakeCreate(response)
    conv = _conversation_with_client(SimpleNamespace(chat=SimpleNamespace(completions=create)))
    out = await conv.call_llm([{"role": "user", "content": "build"}])
    assert out["status"] == "error" and out["code"] == code
    assert out["finish_reason"] == finish_reason and out["request_id"] == "provider-sync"
    assert out["max_tokens"] == 200 and out["usage"]["completion_tokens"] == 5


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
    first_tokens = []
    monkeypatch.setattr(conversation_core, "_record_llm_metrics", lambda duration, usage, **kwargs: recorded.append(usage))
    monkeypatch.setattr(
        conversation_core,
        "_record_llm_first_token_metrics",
        lambda duration: first_tokens.append(duration),
    )

    chunks = []
    async for chunk in conv.call_llm_stream([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    assert "".join(chunks) == "hello"
    assert create.calls[0]["stream_options"] == {"include_usage": True}
    assert recorded == [{"prompt_tokens": 20, "completion_tokens": 7}]
    assert len(first_tokens) == 1


@pytest.mark.asyncio
async def test_call_llm_stream_projects_provider_reasoning_separately(monkeypatch):
    async def stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="consider "))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="answer", reasoning_content="sources"))],
            usage=None,
        )

    create = _FakeCreate(stream())
    client = SimpleNamespace(chat=SimpleNamespace(completions=create))
    conv = _conversation_with_client(client)
    reasoning = []

    async def reasoning_sink(delta):
        reasoning.append(delta)

    chunks = []
    async for chunk in conv.call_llm_stream(
        [{"role": "user", "content": "hi"}],
        reasoning_sink=reasoning_sink,
    ):
        chunks.append(chunk)

    assert chunks == ["answer"]
    assert reasoning == ["consider ", "sources"]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason,code", [("length", "MODEL_OUTPUT_LIMIT"), ("stop", "MODEL_EMPTY_RESPONSE")])
async def test_reasoning_only_stream_reports_provider_terminal_facts(finish_reason, code):
    async def stream():
        yield SimpleNamespace(id="provider-1", choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="think"), finish_reason=None)], usage=None)
        yield SimpleNamespace(id="provider-1", choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish_reason)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=200))

    create = _FakeCreate(stream())
    conv = _conversation_with_client(SimpleNamespace(chat=SimpleNamespace(completions=create)))
    recorded = []

    async def result_sink(result):
        recorded.append(result)

    output = [chunk async for chunk in conv.call_llm_stream([{"role": "user", "content": "build"}], result_sink=result_sink)]
    assert output == [f"[error] {code}"]
    assert recorded[0]["status"] == "error"
    assert recorded[0]["finish_reason"] == finish_reason
    assert recorded[0]["request_id"] == "provider-1"
    assert recorded[0]["max_tokens"] == 200
    assert recorded[0]["reasoning_chars"] == 5


@pytest.mark.asyncio
async def test_multimodal_request_uses_dedicated_model_only_after_main_rejects_modality(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="I can see the diagram"))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=6),
    )
    main_create = _FailingCreate(_UnsupportedImageError())
    multimodal_create = _FakeCreate(response)
    clients = {
        "https://main.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=main_create)),
        "https://vision.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=multimodal_create)),
    }
    conv = _conversation_with_client(clients["https://main.test/v1"])
    conv._get_client_params = lambda user_config=None, user_id=None: (
        "main-key", "https://main.test/v1", "text-model", 0.2, 200, [],
    )
    conv._resolve_async_client = lambda user_config, api_key, base_url: clients[base_url]
    monkeypatch.setattr(conversation_core, "resolve_multimodal_runtime_settings", lambda *args, **kwargs: {
        "api_key": "vision-key",
        "base_url": "https://vision.test/v1",
        "model": "vision-model",
    })

    out = await conv.call_llm([{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }])

    assert out["content"] == "I can see the diagram"
    assert out["model_used"] == "vision-model"
    assert out["model_route"] == "multimodal"
    assert main_create.calls[0]["model"] == "text-model"
    assert multimodal_create.calls[0]["model"] == "vision-model"


@pytest.mark.asyncio
async def test_generic_main_failure_does_not_misroute_to_multimodal_model(monkeypatch):
    generic_error = RuntimeError("temporary connection failure")
    main_create = _FailingCreate(generic_error)
    multimodal_create = _FakeCreate(SimpleNamespace(choices=[], usage=None))
    clients = {
        "https://main-generic.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=main_create)),
        "https://vision-generic.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=multimodal_create)),
    }
    conv = _conversation_with_client(clients["https://main-generic.test/v1"])
    conv._get_client_params = lambda user_config=None, user_id=None: (
        "main-key", "https://main-generic.test/v1", "unknown-model", 0.2, 200, [],
    )
    conv._resolve_async_client = lambda user_config, api_key, base_url: clients[base_url]
    monkeypatch.setattr(conversation_core, "resolve_multimodal_runtime_settings", lambda *args, **kwargs: {
        "api_key": "vision-key",
        "base_url": "https://vision-generic.test/v1",
        "model": "vision-model",
    })

    out = await conv.call_llm([{
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
    }])

    assert out["status"] == "error"
    assert multimodal_create.calls == []


@pytest.mark.asyncio
async def test_multimodal_stream_falls_back_before_emitting_content(monkeypatch):
    async def stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="visible"))],
            usage=None,
        )

    main_create = _FailingCreate(_UnsupportedImageError())
    multimodal_create = _FakeCreate(stream())
    clients = {
        "https://main-stream.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=main_create)),
        "https://vision-stream.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=multimodal_create)),
    }
    conv = _conversation_with_client(clients["https://main-stream.test/v1"])
    conv._get_client_params = lambda user_config=None, user_id=None: (
        "main-key", "https://main-stream.test/v1", "text-stream-model", 0.2, 200, [],
    )
    conv._resolve_async_client = lambda user_config, api_key, base_url: clients[base_url]
    monkeypatch.setattr(conversation_core, "resolve_multimodal_runtime_settings", lambda *args, **kwargs: {
        "api_key": "vision-key",
        "base_url": "https://vision-stream.test/v1",
        "model": "vision-stream-model",
    })

    chunks = []
    async for chunk in conv.call_llm_stream([{
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
    }]):
        chunks.append(chunk)

    assert chunks == ["visible"]
    assert main_create.calls[0]["model"] == "text-stream-model"
    assert multimodal_create.calls[0]["model"] == "vision-stream-model"


@pytest.mark.asyncio
async def test_interrupted_stream_does_not_concatenate_a_fallback_models_output():
    async def broken():
        yield SimpleNamespace(id="partial", choices=[SimpleNamespace(delta=SimpleNamespace(content='{"action":"tool_call"'), finish_reason=None)], usage=None)
        raise ConnectionError("stream disconnected")

    async def fallback():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="unrelated fallback answer"))], usage=None)

    create = _SequenceCreate([broken(), fallback()])
    conv = _conversation_with_client(SimpleNamespace(chat=SimpleNamespace(completions=create)))
    conv._resolve_model_candidates = lambda *_args: ["primary", "fallback"]
    terminal = []

    async def capture(result):
        terminal.append(result)

    chunks = [chunk async for chunk in conv.call_llm_stream([{"role": "user", "content": "act"}], result_sink=capture)]
    assert chunks == ['{"action":"tool_call"', "[error] stream disconnected"]
    assert len(create.calls) == 1
    assert terminal[0]["code"] == "MODEL_STREAM_INTERRUPTED"


@pytest.mark.asyncio
async def test_failed_dedicated_endpoint_degrades_to_text_context(monkeypatch):
    text_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Used OCR fallback"))],
        usage=None,
    )
    main_create = _SequenceCreate([_UnsupportedImageError(), text_response])
    dedicated_create = _FailingCreate(RuntimeError("dedicated endpoint unavailable"))
    clients = {
        "https://main-degrade.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=main_create)),
        "https://vision-degrade.test/v1": SimpleNamespace(chat=SimpleNamespace(completions=dedicated_create)),
    }
    conv = _conversation_with_client(clients["https://main-degrade.test/v1"])
    conv._get_client_params = lambda user_config=None, user_id=None: (
        "main-key", "https://main-degrade.test/v1", "text-degrade-model", 0.2, 200, [],
    )
    conv._resolve_async_client = lambda user_config, api_key, base_url: clients[base_url]
    monkeypatch.setattr(conversation_core, "resolve_multimodal_runtime_settings", lambda *args, **kwargs: {
        "api_key": "vision-key",
        "base_url": "https://vision-degrade.test/v1",
        "model": "vision-degrade-model",
    })

    out = await conv.call_llm([{
        "role": "user",
        "content": [
            {"type": "text", "text": "OCR says revenue increased"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }])

    assert out["content"] == "Used OCR fallback"
    assert out["model_route"] == "text_fallback"
    assert all(part.get("type") == "text" for part in main_create.calls[1]["messages"][0]["content"])
