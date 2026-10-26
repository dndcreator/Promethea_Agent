from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentkit.tools.standard.web_search_runtime import (
    WebSearchError,
    WebSearchProvider,
    WebSearchRuntime,
    WebSearchSettings,
)
from agentkit.tools.standard.web_tools import WebSearchTool
from gateway.events import EventEmitter
from gateway.runtime_event_log import RuntimeEventLog
from gateway.capability_service import ToolInvocationContext, CapabilityService


class _Provider(WebSearchProvider):
    def __init__(
        self,
        provider_id: str,
        *,
        priority: int = 100,
        available: bool = True,
        fallback: bool = False,
        error: WebSearchError | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.label = provider_id
        self.priority = priority
        self.fallback = fallback
        self.available = available
        self.error = error
        self.calls = 0

    def is_available(self, settings: WebSearchSettings) -> bool:
        _ = settings
        return self.available

    async def search(self, query: str, max_results: int, settings: WebSearchSettings):
        _ = settings
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "query": query,
            "provider": self.provider_id,
            "count": 1,
            "results": [{"title": self.provider_id, "url": f"https://{self.provider_id}.example"}],
            "truncated": False,
            "max_results": max_results,
        }


def test_runtime_rejects_duplicate_provider_ids():
    runtime = WebSearchRuntime([_Provider("one")])

    with pytest.raises(WebSearchError) as exc_info:
        runtime.register_provider(_Provider("one"))

    assert exc_info.value.code == "SEARCH_PROVIDER_DUPLICATE"


@pytest.mark.asyncio
async def test_auto_selection_uses_provider_priority_not_registration_order():
    slower_priority = _Provider("later", priority=20)
    preferred = _Provider("preferred", priority=10)
    runtime = WebSearchRuntime([slower_priority, preferred])

    result = await runtime.search("query", 8, WebSearchSettings())

    assert result["provider"] == "preferred"
    assert result["fallback_used"] is False
    assert preferred.calls == 1
    assert slower_priority.calls == 0


@pytest.mark.asyncio
async def test_explicit_provider_failure_uses_registered_fallback():
    primary = _Provider(
        "primary",
        priority=10,
        error=WebSearchError("failed", "SEARCH_PROVIDER_ERROR", retryable=True),
    )
    fallback = _Provider("free", fallback=True)
    runtime = WebSearchRuntime([fallback, primary])

    result = await runtime.search("query", 8, WebSearchSettings(provider="primary"))

    assert result["provider"] == "free"
    assert result["fallback_used"] is True
    assert result["provider_errors"][0]["code"] == "SEARCH_PROVIDER_ERROR"


@pytest.mark.asyncio
async def test_configured_provider_order_overrides_declared_priority():
    preferred = _Provider("preferred", priority=100)
    default_first = _Provider("default-first", priority=10)
    runtime = WebSearchRuntime([default_first, preferred])

    result = await runtime.search(
        "query",
        8,
        WebSearchSettings(provider_order=("preferred", "default-first")),
    )

    assert result["provider"] == "preferred"


@pytest.mark.asyncio
async def test_strict_policy_does_not_silently_switch_provider():
    primary = _Provider(
        "primary",
        priority=10,
        error=WebSearchError("failed", "SEARCH_PROVIDER_ERROR", retryable=True),
    )
    fallback = _Provider("free", fallback=True)
    runtime = WebSearchRuntime([fallback, primary])

    with pytest.raises(WebSearchError) as exc_info:
        await runtime.search(
            "query",
            8,
            WebSearchSettings(provider="primary", fallback_policy="strict"),
        )

    assert exc_info.value.code == "SEARCH_PROVIDER_ERROR"
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_strict_policy_does_not_use_fallback_when_provider_is_unavailable():
    primary = _Provider("primary", available=False)
    fallback = _Provider("free", fallback=True)
    runtime = WebSearchRuntime([fallback, primary])

    with pytest.raises(WebSearchError) as exc_info:
        await runtime.search(
            "query",
            8,
            WebSearchSettings(provider="primary", fallback_policy="strict"),
        )

    assert exc_info.value.code == "SEARCH_PROVIDER_UNAVAILABLE"
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_runtime_reports_structured_error_when_all_providers_fail():
    runtime = WebSearchRuntime(
        [_Provider("broken", error=WebSearchError("offline", "SEARCH_PROVIDER_UNAVAILABLE", retryable=True))]
    )

    with pytest.raises(WebSearchError) as exc_info:
        await runtime.search("query", 8, WebSearchSettings())

    assert exc_info.value.code == "SEARCH_PROVIDER_ERROR"
    assert exc_info.value.retryable is True
    assert exc_info.value.details["provider_errors"][0]["provider"] == "broken"


@pytest.mark.asyncio
async def test_runtime_preserves_cancellation():
    class _BlockingProvider(_Provider):
        async def search(self, query: str, max_results: int, settings: WebSearchSettings):
            _ = (query, max_results, settings)
            await asyncio.Event().wait()

    task = asyncio.create_task(
        WebSearchRuntime([_BlockingProvider("blocking")]).search("query", 8, WebSearchSettings())
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["strict", "fallback"])
async def test_empty_results_follow_existing_fallback_policy(policy):
    class Empty(_Provider):
        async def search(self, query, max_results, settings):
            self.calls += 1
            return {"query": query, "provider": self.provider_id, "count": 0, "results": [], "truncated": False}
    first, second = Empty("one", priority=1), _Provider("two", priority=2)
    result = await WebSearchRuntime([first, second]).search("query", 8, WebSearchSettings(fallback_policy=policy))
    assert second.calls == (policy == "fallback")
    assert result["count"] == (1 if policy == "fallback" else 0)
    assert result["attempts"][0] == {"provider": "one", "status": "empty"}


@pytest.mark.asyncio
async def test_empty_then_error_remains_honest_zero_not_a_fabricated_failure():
    class Empty(_Provider):
        async def search(self, query, max_results, settings):
            return {"query": query, "provider": self.provider_id, "count": 0, "results": [], "truncated": False}
    result = await WebSearchRuntime([Empty("empty", priority=1), _Provider("offline", error=WebSearchError("offline", "SEARCH_TIMEOUT"))]).search("query", 8, WebSearchSettings())
    assert result["count"] == 0
    assert [row["status"] for row in result["attempts"]] == ["empty", "error"]
    assert result["provider_errors"][0]["code"] == "SEARCH_TIMEOUT"


@pytest.mark.asyncio
async def test_duckduckgo_uses_structural_parsing_snippets_and_actual_target_urls(monkeypatch):
    from agentkit.tools.standard import web_search_runtime as module
    async def page(*args, **kwargs):
        return '''<div class="result result--web"><h2><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fdoc%3Fv%3D2&amp;rut=ignored" data-extra="1" class="extra result__a"><span>Verified</span> document</a></h2><a class="result__snippet">Read <b>this</b> content.</a></div><a class="result__a" href="javascript:alert(1)">Unsafe</a>'''
    monkeypatch.setattr(module, "_http_text", page)
    result = await module.DuckDuckGoSearchProvider().search("example", 8, WebSearchSettings())
    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.org/doc?v=2"
    assert result["results"][0]["title"] == "Verified document"
    assert result["results"][0]["snippet"] == "Read this content."


@pytest.mark.asyncio
async def test_only_searxng_sets_the_configured_service_boundary(monkeypatch):
    from agentkit.tools.standard import web_search_runtime as module
    calls = []
    async def request(url, **kwargs):
        calls.append((url, kwargs))
        return {"results": [], "organic_results": []}
    monkeypatch.setattr(module, "_http_json", request)
    await module.SearxngSearchProvider().search("topic", 8, WebSearchSettings(values={"searxng_url": "http://127.0.0.1:8888/prefix"}))
    assert calls[-1][0].startswith("http://127.0.0.1:8888/prefix/search?")
    assert calls[-1][1]["service_url"] == "http://127.0.0.1:8888/prefix"
    await module.SerpApiSearchProvider().search("topic", 8, WebSearchSettings(values={"serpapi_api_key": "test-only"}))
    assert "service_url" not in calls[-1][1]


@pytest.mark.asyncio
async def test_public_tool_keeps_provider_policy_out_of_model_args(monkeypatch, tmp_path: Path):
    configured = _Provider("configured")
    runtime = WebSearchRuntime([configured])
    tool = WebSearchTool(runtime=runtime)
    monkeypatch.setattr(
        "agentkit.tools.standard.web_tools.resolve_search_runtime_settings",
        lambda _user_id: {"provider": "configured"},
    )

    result = await tool.invoke(
        {"query": "promethea", "provider": "model-selected", "user_id": "other-user"},
        ToolInvocationContext(user_id="real-user"),
    )

    assert result["provider"] == "configured"
    assert "providers" not in result
    assert set(tool.input_schema["properties"]) == {"query"}


@pytest.mark.asyncio
async def test_search_result_projection_is_persisted_without_raw_provider_payload(monkeypatch, tmp_path: Path):
    runtime = WebSearchRuntime([_Provider("configured")])
    tool = WebSearchTool(runtime=runtime)
    monkeypatch.setattr(
        "agentkit.tools.standard.web_tools.resolve_search_runtime_settings",
        lambda _user_id: {"provider": "configured"},
    )
    event_log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    service = CapabilityService(event_emitter=EventEmitter(event_log))
    service.register_tool(tool)

    result = await service.call_tool(
        "web.search",
        {"query": "promethea"},
        ctx=ToolInvocationContext(user_id="u1", session_id="s1"),
    )

    assert result["provider"] == "configured"
    rows = event_log.query(user_id="u1", event_type="tool.call.result")
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["result_summary"] == "Found 1 sources via configured"
    assert payload["result_metadata"]["kind"] == "web_search"
    assert payload["result_metadata"]["sources"][0]["url"] == "https://configured.example"
    assert "result" not in payload

    spec = service.tool_registry.resolve(tool_name="web.search", params={})
    assert spec.input_schema == tool.input_schema
    assert spec.output_schema == tool.output_schema
