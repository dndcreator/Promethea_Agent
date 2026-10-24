import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.model_pricing import ModelPricing, PricingSettings, estimate
from gateway.http.metrics import MetricsCollector


def settings(**values):
    return PricingSettings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_exact_endpoint_and_model_no_cross_provider_price_guessing():
    pricing = ModelPricing(settings(rates=[{"base_url": "https://custom.test/v1", "model": "exact-model", "input_per_million": "2", "output_per_million": "6", "cache_read_per_million": "0.2"}]))
    quote = await pricing.quote("https://custom.test/v1/", "exact-model")
    result = estimate(quote, {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 400})
    assert result["estimated_usd"] == pytest.approx(0.00188)
    assert quote["source"] == "operator_env" and quote["revision"]
    assert await pricing.quote("https://other.test/v1", "exact-model") is None
    assert await pricing.quote("https://custom.test/v1", "model-alias") is None
    assert estimate(quote, {"prompt_tokens": 1000, "completion_tokens": 100}) is None
    assert estimate(quote, {"prompt_tokens": 100, "completion_tokens": 100, "prompt_cache_hit_tokens": 200}) is None


@pytest.mark.asyncio
async def test_catalog_refresh_caches_and_never_reprices_recorded_cost():
    now = [1000]
    pricing = ModelPricing(settings(cache_ttl_s=60), clock=lambda: now[0])
    pricing._fetch = AsyncMock(return_value={"data": [{"id": "vendor/model", "pricing": {"prompt": "0.000002", "completion": "0.000006", "input_cache_read": "0.0000002"}}]})
    old = await pricing.quote(pricing.endpoint, "vendor/model")
    collector = MetricsCollector()
    collector.record_llm_call(0.1, 100, 10, cost_estimate=estimate(old, {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 0}}))
    original = collector.get_stats()["cost"]["estimated_usd"]
    await pricing.quote(pricing.endpoint, "vendor/model")
    assert pricing._fetch.await_count == 1
    now[0] += 61
    pricing._fetch.return_value["data"][0]["pricing"]["prompt"] = "0.000004"
    new = await pricing.quote(pricing.endpoint, "vendor/model")
    assert new["revision"] != old["revision"] and old["input"] == "0.000002"
    assert collector.get_stats()["cost"]["estimated_usd"] == original
    pricing._fetch.side_effect = TimeoutError()
    now[0] += 61
    assert await pricing.quote(pricing.endpoint, "vendor/model") is None
    await pricing.quote(pricing.endpoint, "vendor/model")
    assert pricing._fetch.await_count == 3


@pytest.mark.asyncio
async def test_variable_unsupported_missing_and_invalid_rates_remain_unknown():
    pricing = ModelPricing(settings())
    pricing._fetch = AsyncMock(return_value={"data": [
        {"id": "valid-free", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "scheduled", "pricing": {"prompt": "1", "completion": "2", "overrides": [{"prompt": "3"}]}},
        {"id": "extra-charge", "pricing": {"prompt": "1", "completion": "2", "request": "0.01"}},
        {"id": "invalid", "pricing": {"prompt": "NaN", "completion": "2"}},
        {"id": "missing", "pricing": {"prompt": "1"}},
    ]})
    for name in ("scheduled", "extra-charge", "invalid", "missing", "unknown"):
        assert await pricing.quote(pricing.endpoint, name) is None
    quote = await pricing.quote(pricing.endpoint, "valid-free")
    assert estimate(quote, {"prompt_tokens": 10, "completion_tokens": 2})["estimated_usd"] == 0
    assert estimate(quote, {"prompt_tokens": -1, "completion_tokens": 2}) is None
    assert estimate(quote, {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": []}) is not None  # Empty optional details.
    assert estimate(quote, {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": "invalid"}) is None


@pytest.mark.asyncio
async def test_refresh_is_single_flight_and_cancellation_propagates():
    pricing = ModelPricing(settings())
    started, release = asyncio.Event(), asyncio.Event()
    async def fetch():
        started.set()
        await release.wait()
        return {"data": []}
    pricing._fetch = AsyncMock(side_effect=fetch)
    first = asyncio.create_task(pricing.quote(pricing.endpoint, "a"))
    await started.wait()
    second = asyncio.create_task(pricing.quote(pricing.endpoint, "b"))
    release.set()
    await first
    await second
    assert pricing._fetch.await_count == 1
    pricing._expires = 0
    pricing._fetch.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await pricing.quote(pricing.endpoint, "a")


def test_partial_coverage_is_not_a_fake_total_and_zero_price_is_distinct():
    collector = MetricsCollector()
    collector.record_llm_call(.1, 100, 10, cost_estimate={"estimated_usd": 0.2})
    collector.record_llm_call(.1, 200, 20)
    row = collector.get_stats()
    assert row["llm"]["estimated_cost"] is None
    assert row["cost"]["known_estimated_usd"] == .2 and row["cost"]["unpriced_calls"] == 1
    collector.reset()
    collector.record_llm_call(.1, 100, 10, cost_estimate={"estimated_usd": 0})
    assert collector.get_stats()["cost"]["estimated_usd"] == 0


def test_env_configuration_and_duplicate_rate_rejection(monkeypatch):
    monkeypatch.setenv("PRICING__AUTO_REFRESH", "false")
    monkeypatch.setenv("PRICING__RATES", '[{"base_url":"https://example.test/v1","model":"m","input_per_million":"1","output_per_million":"2"}]')
    config = settings()
    assert not config.auto_refresh and config.rates[0].model == "m"
    monkeypatch.delenv("PRICING__RATES")
    rate = {"base_url": "https://a.test/v1", "model": "a", "input_per_million": "0", "output_per_million": "0"}
    with pytest.raises(ValueError, match="duplicate"):
        settings(rates=[rate, rate])


@pytest.mark.asyncio
async def test_model_io_retains_quote_and_cached_usage_without_changing_answer(monkeypatch):
    import conversation_core
    from tests.test_conversation_core_metrics import _conversation_with_client, _FakeCreate
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))], usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10, prompt_cache_hit_tokens=40))
    client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCreate(response)))
    pricing = ModelPricing(settings(rates=[{"base_url": "https://example.test/v1", "model": "model-a", "input_per_million": "2", "output_per_million": "6", "cache_read_per_million": "0.2"}]))
    monkeypatch.setattr("gateway.model_pricing.quote_model", pricing.quote)
    output = await _conversation_with_client(client).call_llm([{"role": "user", "content": "hi"}])
    assert output["content"] == "answer" and output["status"] == "success"
    assert output["usage"]["prompt_cache_hit_tokens"] == 40
    assert output["cost_estimate"]["estimated_usd"] == pytest.approx(0.000188)


@pytest.mark.asyncio
async def test_action_audit_persists_the_call_quote_in_existing_event_log(tmp_path):
    from gateway.action import ActionService
    from gateway.action.models import ActionContext, ActionRun
    from gateway.events import EventEmitter
    from gateway.runtime_event_log import RuntimeEventLog
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter()
    emitter.attach_event_log(log)
    service = ActionService(conversation_core=None, event_emitter=emitter)
    run = ActionRun(goal="hello", messages=[], context=ActionContext(user_id="alice", session_id="chat"))
    quote = {"estimated_usd": .01, "pricing": {"revision": "old-rate", "source": "operator_env", "model": "m"}}
    await service._record_model_call(run, messages=[{"role": "user", "content": "hello"}], model_step_id="step1", response={"status": "success", "content": "answer", "cost_estimate": quote}, source="runtime")
    restored = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    assert restored.query(user_id="alice")[0]["payload"]["cost_estimate"] == quote
