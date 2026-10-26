import asyncio
import hashlib

import pytest
from aiohttp import web

from agentkit.security.http import HttpDocument, request_document, _Resolver
from agentkit.security.sandbox import SandboxPolicy
from agentkit.tools.web_content import extract_page, fetch_page


ARTICLE = '''<html><head><title>Release notes</title></head><body>
<nav>NOISY NAVIGATION <a href="/account">account</a></nav>
<article><h1>Verified release information</h1>
<p>The release has 47 documented changes. Review actual source content rather than a search snippet. This paragraph is part of the main article.</p>
<p>The current version requires explicit approval before external writes. These requirements apply to every execution path.</p>
<table><tr><th>Version</th><th>Changes</th></tr><tr><td>Preview</td><td>47</td></tr></table>
<a href="/details">Further details</a></article>
<script>window.secret = "SCRIPT NOISE";</script><style>STYLE NOISE</style>
<footer>FOOTER NOISE</footer></body></html>'''


def test_article_extraction_removes_markup_and_noise_but_retains_content_and_table():
    result = extract_page(ARTICLE, url="https://example.org/article", include_links=True)
    assert result["title"] == "Release notes" and result["read_status"] == "read"
    assert "47" in result["text"] and "explicit approval" in result["text"]
    assert not any(noise in result["text"] for noise in ("NOISY NAVIGATION", "SCRIPT NOISE", "STYLE NOISE", "FOOTER NOISE", "<p>"))
    assert "https://example.org/details" in result["links"]
    assert result["content_sha256"] == hashlib.sha256(result["text"].encode()).hexdigest()


def test_plain_text_and_truncation_are_not_silently_treated_as_complete_html():
    result = extract_page("a" * 100, url="https://example.org/data", content_type="text/plain", max_chars=17)
    assert result["text"] == "a" * 17 and result["truncated"]
    assert result["extraction_method"] == "plain_text"
    with pytest.raises(ValueError, match="unsupported"):
        extract_page("not a parsed pdf", url="https://example.org/file", content_type="application/pdf")
    empty = extract_page("<html><body><script>dynamic()</script></body></html>", url="https://example.org/dynamic")
    assert empty["read_status"] == "empty" and empty["text"] == ""


@pytest.mark.asyncio
async def test_two_web_readers_share_extraction_and_preserve_legacy_envelopes(monkeypatch):
    from agentkit.tools.standard.web_tools import WebFetchTextTool
    from agentkit.tools.content_tools.content_tools import ContentToolsService
    async def retrieve(url, **kwargs):
        return HttpDocument("https://example.org/final", 200, "text/html; charset=utf-8", "utf-8", ARTICLE.encode())
    monkeypatch.setattr("agentkit.tools.web_content.request_document", retrieve)
    first = await WebFetchTextTool().invoke({"url": "https://example.org/start"})
    second = await ContentToolsService().web_fetch("https://example.org/start")
    assert first["text"] == second["content"]
    assert first["source_id"] == second["source_id"]
    assert first["final_url"] == "https://example.org/final"
    assert first["fetched_at"] > 0 and second["status_code"] == 200
    assert "text" not in second


def test_private_service_exception_is_exact_operator_scoped_and_never_global():
    policy = SandboxPolicy(allowed_service_urls=["http://127.0.0.1:8888/searx"])
    assert policy.check_service_url("http://127.0.0.1:8888/searx/search?q=x", service_url="http://127.0.0.1:8888/searx").allowed
    for url in ("http://127.0.0.1:8888/admin", "http://127.0.0.1:8889/searx/search", "http://127.0.0.1:8888/searx/../admin"):
        assert not policy.check_service_url(url, service_url="http://127.0.0.1:8888/searx").allowed
    assert not policy.check_url("http://127.0.0.1:8888/searx/search").allowed
    assert not SandboxPolicy(network_mode="none", allowed_service_urls=["http://127.0.0.1:8888"]).check_service_url("http://127.0.0.1:8888/search", service_url="http://127.0.0.1:8888").allowed


@pytest.mark.asyncio
async def test_dns_resolution_cannot_turn_an_allowed_public_name_into_loopback():
    resolver = _Resolver(allow_private=False)
    class Fake:
        async def resolve(self, *args):
            return [{"host": "127.0.0.1", "port": 80}]
        async def close(self):
            pass
    await resolver.delegate.close()
    resolver.delegate = Fake()
    try:
        with pytest.raises(PermissionError, match="DNS"):
            await resolver.resolve("public.example", 80)
    finally:
        await resolver.close()


@pytest.mark.asyncio
async def test_real_local_service_redirect_size_and_cancellation_boundaries(monkeypatch):
    reached = []
    async def handler(request):
        reached.append(request.path)
        if request.path == "/search":
            return web.json_response({"results": []})
        if request.path == "/redirect":
            raise web.HTTPFound("http://127.0.0.1:1/secret")
        if request.path == "/slow":
            await asyncio.sleep(1)
        return web.Response(text="x" * 5000)
    app = web.Application();app.router.add_get('/{path:.*}', handler)
    runner = web.AppRunner(app);await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0);await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    policy = SandboxPolicy(allowed_service_urls=[base])
    try:
        response = await request_document(base + "/search", policy=policy, service_url=base)
        assert response.status == 200
        with pytest.raises(PermissionError):
            await request_document(base + "/search", policy=policy)
        with pytest.raises(PermissionError):
            await request_document(base + "/redirect", policy=policy, service_url=base)
        with pytest.raises(ValueError, match="byte limit"):
            await request_document(base + "/large", policy=policy, service_url=base, max_bytes=100)
        task = asyncio.create_task(request_document(base + "/slow", policy=policy, service_url=base))
        await asyncio.sleep(0.05);task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async def rebinding(self, host, port=0, family=0):
            return [{"hostname": host, "host": "127.0.0.1", "port": port, "family": 2, "proto": 0, "flags": 0}]
        with monkeypatch.context() as patch:
            patch.setattr("aiohttp.ThreadedResolver.resolve", rebinding)
            with pytest.raises(PermissionError, match="DNS"):
                await request_document(base.replace("127.0.0.1", "public.example") + "/secret", policy=policy)
        assert "/secret" not in reached
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_retrieved_body_provenance_uses_existing_durable_tool_event(monkeypatch, tmp_path):
    from agentkit.tools.standard.web_tools import WebFetchTextTool
    from gateway.capability_service import CapabilityService, ToolInvocationContext
    from gateway.events import EventEmitter
    from gateway.runtime_event_log import RuntimeEventLog
    async def retrieve(url, **kwargs):
        return HttpDocument(url, 200, "text/html", "utf-8", ARTICLE.encode())
    monkeypatch.setattr("agentkit.tools.web_content.request_document", retrieve)
    path = str(tmp_path / "events.jsonl")
    service = CapabilityService(event_emitter=EventEmitter(RuntimeEventLog(storage_path=path)))
    service.register_tool(WebFetchTextTool())
    result = await service.call_tool("web.fetch_text", {"url": "https://example.org/article"}, ctx=ToolInvocationContext(user_id="alice", session_id="chat"))
    restored = RuntimeEventLog(storage_path=path)
    records = restored.query(user_id="alice", event_type="tool.call.result")
    evidence = records[0]["payload"]["result_metadata"]
    assert evidence["text_preview"] == result["text"][:600] and evidence["source_id"] == result["source_id"]
    assert "text" not in evidence  # Full text belongs to the existing Action Observation, not a second evidence store.
    assert evidence["fetched_at"] and evidence["title"] == "Release notes"
    assert not restored.query(user_id="bob", event_type="tool.call.result")


@pytest.mark.asyncio
async def test_existing_action_loop_searches_reads_searches_again_and_retains_actual_evidence(monkeypatch, tmp_path):
    from agentkit.tools.standard.web_tools import WebSearchTool, WebFetchTextTool
    from agentkit.tools.standard.web_search_runtime import WebSearchRuntime
    from tests.test_web_search_runtime import _Provider
    from tests.test_ambient_service import Core, call, setup
    from tests.test_background_agents import parent
    from gateway.events import EventEmitter
    from gateway.runtime_event_log import RuntimeEventLog
    from gateway.protocol import EventType

    query_calls = []
    class Search(_Provider):
        async def search(self, query, max_results, settings):
            query_calls.append(query)
            result = await super().search(query, max_results, settings)
            result["results"][0]["url"] = "https://example.org/article" if len(query_calls) == 1 else "https://example.org/verification"
            result["results"][0]["snippet"] = "A teaser, not the page's full evidence."
            return result
    async def retrieve(url, **kwargs):
        body = ARTICLE if url.endswith("/article") else ARTICLE.replace("47", "48").replace("Release notes", "Correction")
        return HttpDocument(url, 200, "text/html", "utf-8", body.encode())
    monkeypatch.setattr("agentkit.tools.web_content.request_document", retrieve)
    monkeypatch.setattr("agentkit.tools.standard.web_tools.resolve_search_runtime_settings", lambda _: {"provider": "fixture"})
    core = Core(call("web.search", query="release changes"), call("web.fetch_text", url="https://example.org/article"),
                call("web.search", query="verify release changes correction"), call("web.fetch_text", url="https://example.org/verification"),
                {"action": "answer", "content": "The correction says 48, not 47. [Correction](https://example.org/verification)"})
    _, runtime, conversation, _, _ = setup(tmp_path, core)
    log_path = str(tmp_path / "research.jsonl")
    events = EventEmitter(RuntimeEventLog(storage_path=log_path))
    conversation.event_emitter = conversation.action_service.event_emitter = conversation.capability_service.event_emitter = events
    conversation.capability_service.register_tool(WebSearchTool(runtime=WebSearchRuntime([Search("fixture")])))
    conversation.capability_service.register_tool(WebFetchTextTool())
    from gateway.capability_service import ToolInvocationContext
    context = parent()
    async def execute(name, arguments):
        return await conversation.capability_service.call_tool(name, arguments, run_context=context, user_config={},
                                                               ctx=ToolInvocationContext(user_id="alice", session_id="chat"))
    try:
        result = await conversation.run_chat_loop([{"role": "user", "content": "Research and verify the release count."}],
                                                user_config={}, session_id="chat", user_id="alice", run_context=context, max_recursion=6, tool_executor=execute)
        assert result["status"] == "success" and "48, not 47" in result["content"]
        assert query_calls == ["release changes", "verify release changes correction"]
        assert "explicit approval" in str(core.requests[-1]) and "48" in str(core.requests[-1])
        restored = RuntimeEventLog(storage_path=log_path)
        observations = restored.query(user_id="alice", event_type=EventType.ACTION_OBSERVATION_COMMITTED.value)
        reads = [row["payload"]["structured_result"] for row in observations if row["payload"].get("tool_name") == "web.fetch_text"]
        assert len(reads) == 2 and all(row["source_id"] and row["text"] and row["fetched_at"] for row in reads)
        assert reads[0]["source_id"] != reads[1]["source_id"]
        assert all("SCRIPT NOISE" not in row["text"] for row in reads)
    finally:
        await runtime.shutdown()
