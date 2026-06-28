from __future__ import annotations

import abc
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from agentkit.security.sandbox import get_sandbox_policy


SEARCH_PROVIDER_IDS = ("auto", "brave", "tavily", "serpapi", "searxng", "duckduckgo")


@dataclass(frozen=True)
class WebSearchSettings:
    provider: str = "auto"
    brave_api_key: str = ""
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    searxng_url: str = ""


class WebSearchProvider(abc.ABC):
    provider_id: str
    label: str
    requires_key: bool = False

    def is_available(self, settings: WebSearchSettings) -> bool:
        return True

    @abc.abstractmethod
    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        raise NotImplementedError


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout_s: int = 20,
) -> Dict[str, Any]:
    decision = get_sandbox_policy().check_url(url)
    if not decision.allowed:
        raise PermissionError(f"sandbox blocked url: {decision.reason}")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "PrometheaAgent/1.0",
            "Accept": "application/json",
            **(headers or {}),
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(raw.decode(charset, errors="replace"))


def _http_text(url: str, *, headers: Optional[Dict[str, str]] = None, timeout_s: int = 20) -> str:
    decision = get_sandbox_policy().check_url(url)
    if not decision.allowed:
        raise PermissionError(f"sandbox blocked url: {decision.reason}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PrometheaAgent/1.0", **(headers or {})},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        return resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")


def _clean_text(value: Any) -> str:
    text = re.sub(r"<.*?>", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _result(title: Any, url: Any, snippet: Any = "", source: Any = "") -> Dict[str, Any]:
    return {
        "title": _clean_text(title),
        "url": str(url or "").strip(),
        "snippet": _clean_text(snippet),
        "source": _clean_text(source),
    }


def _compact_results(rows: Iterable[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        compact.append(row)
        if len(compact) >= max_results:
            break
    return compact


class BraveSearchProvider(WebSearchProvider):
    provider_id = "brave"
    label = "Brave Search"
    requires_key = True

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.brave_api_key)

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": max_results}
        )
        payload = _http_json(url, headers={"X-Subscription-Token": settings.brave_api_key})
        rows = (
            _result(item.get("title"), item.get("url"), item.get("description"), item.get("profile", {}).get("name"))
            for item in ((payload.get("web") or {}).get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, _compact_results(rows, max_results))


class TavilySearchProvider(WebSearchProvider):
    provider_id = "tavily"
    label = "Tavily"
    requires_key = True

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.tavily_api_key)

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        body = json.dumps(
            {
                "api_key": settings.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            }
        ).encode("utf-8")
        payload = _http_json(
            "https://api.tavily.com/search",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        rows = (
            _result(item.get("title"), item.get("url"), item.get("content"), "Tavily")
            for item in (payload.get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, _compact_results(rows, max_results))


class SerpApiSearchProvider(WebSearchProvider):
    provider_id = "serpapi"
    label = "SerpAPI"
    requires_key = True

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.serpapi_api_key)

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"engine": "google", "q": query, "num": max_results, "api_key": settings.serpapi_api_key}
        )
        payload = _http_json(url)
        rows = (
            _result(item.get("title"), item.get("link"), item.get("snippet"), item.get("source"))
            for item in (payload.get("organic_results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, _compact_results(rows, max_results))


class SearxngSearchProvider(WebSearchProvider):
    provider_id = "searxng"
    label = "SearXNG"

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.searxng_url)

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        base = settings.searxng_url.rstrip("/")
        if not (base.startswith("http://") or base.startswith("https://")):
            raise ValueError("SEARCH__SEARXNG_URL must start with http:// or https://")
        url = base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        payload = _http_json(url)
        rows = (
            _result(item.get("title"), item.get("url"), item.get("content"), item.get("engine"))
            for item in (payload.get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, _compact_results(rows, max_results))


class DuckDuckGoSearchProvider(WebSearchProvider):
    provider_id = "duckduckgo"
    label = "DuckDuckGo"

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        _ = settings
        endpoint = f"https://duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        html = _http_text(endpoint)
        rows: List[Dict[str, Any]] = []
        for match in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = _clean_text(match.group(1))
            title = _clean_text(match.group(2))
            if href:
                rows.append(_result(title, href, "", "DuckDuckGo"))
        return _search_payload(query, self.provider_id, _compact_results(rows, max_results))


def _search_payload(query: str, provider: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "query": query,
        "provider": provider,
        "count": len(results),
        "results": results,
    }


class WebSearchRuntime:
    def __init__(self, providers: Optional[Iterable[WebSearchProvider]] = None) -> None:
        self.providers = list(
            providers
            or [
                BraveSearchProvider(),
                TavilySearchProvider(),
                SerpApiSearchProvider(),
                SearxngSearchProvider(),
                DuckDuckGoSearchProvider(),
            ]
        )
        self._by_id = {provider.provider_id: provider for provider in self.providers}

    def provider_status(self, settings: WebSearchSettings) -> List[Dict[str, Any]]:
        return [
            {
                "id": provider.provider_id,
                "label": provider.label,
                "available": provider.is_available(settings),
                "requires_key": provider.requires_key,
            }
            for provider in self.providers
        ]

    def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        selected = (settings.provider or "auto").strip().lower()
        if selected not in SEARCH_PROVIDER_IDS:
            raise ValueError(f"unsupported search provider: {selected}")

        errors: List[Dict[str, str]] = []
        for provider in self._provider_order(selected, settings):
            if not provider.is_available(settings):
                errors.append({"provider": provider.provider_id, "error": "not configured"})
                continue
            try:
                payload = provider.search(query, max_results, settings)
                payload["configured_provider"] = selected
                payload["fallback_used"] = selected not in ("", "auto", provider.provider_id)
                if errors:
                    payload["provider_errors"] = errors
                return payload
            except Exception as exc:
                errors.append({"provider": provider.provider_id, "error": str(exc)})

        fallback = self._by_id["duckduckgo"]
        payload = fallback.search(query, max_results, settings)
        payload["configured_provider"] = selected
        payload["fallback_used"] = selected not in ("", "auto", "duckduckgo")
        if errors:
            payload["provider_errors"] = errors
        return payload

    def _provider_order(self, selected: str, settings: WebSearchSettings) -> List[WebSearchProvider]:
        fallback = self._by_id["duckduckgo"]
        if selected and selected != "auto":
            primary = self._by_id.get(selected)
            return [provider for provider in (primary, fallback) if provider is not None]
        auto_order = [provider for provider in self.providers if provider.provider_id != "duckduckgo"]
        configured = [provider for provider in auto_order if provider.is_available(settings)]
        return configured + [fallback]
