from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentkit.mcp.tool_call import ToolConfirmationRequired
from agentkit.tools.web.websearch import WebSearchService


def test_tool_confirmation_required_preserves_dict_payload():
    payload = {"command": "search", "service_name": "websearch", "query": "maotai"}
    exc = ToolConfirmationRequired("call_1", "search", payload, [])

    assert exc.tool_args == payload
    assert isinstance(exc.tool_args, dict)


@pytest.mark.asyncio
async def test_websearch_quick_answer_accepts_question_alias(monkeypatch):
    service = WebSearchService()
    service._sandbox = SimpleNamespace(check_url=lambda _url: SimpleNamespace(allowed=True, reason=""))

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def answers(self, _query):
            return []

    async def _fake_search(query, max_results=None, num_results=None):
        _ = (max_results, num_results)
        return f"fallback:{query}"

    monkeypatch.setattr("agentkit.tools.web.websearch._resolve_ddgs_class", lambda: _FakeDDGS)
    monkeypatch.setattr(service, "search", _fake_search)

    result = await service.quick_answer(question="maotai stock today")
    assert result == "fallback:maotai stock today"
