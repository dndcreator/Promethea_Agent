from __future__ import annotations

import abc
import asyncio
import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

import aiohttp

from agentkit.security.sandbox import get_sandbox_policy


@dataclass(frozen=True)
class WebSearchSettings:
    provider: str = "auto"
    fallback_policy: str = "fallback"
    provider_order: tuple[str, ...] = ()
    values: Mapping[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return str(self.values.get(key, default) or default)


class WebSearchError(RuntimeError):
    category = "web_search"

    def __init__(
        self,
        message: str,
        code: str,
        *,
        retryable: bool = False,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = dict(details or {})


class WebSearchProvider(abc.ABC):
    provider_id: str
    label: str
    requires_key: bool = False
    priority: int = 100
    fallback: bool = False

    def is_available(self, settings: WebSearchSettings) -> bool:
        return True

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        max_results: int,
        settings: WebSearchSettings,
    ) -> Dict[str, Any]:
        raise NotImplementedError


async def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout_s: int = 20,
) -> Dict[str, Any]:
    text = await _http_text(
        url,
        method=method,
        headers={"Accept": "application/json", **(headers or {})},
        body=body,
        timeout_s=timeout_s,
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WebSearchError(
            "search provider returned invalid JSON",
            "SEARCH_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise WebSearchError(
            "search provider returned a non-object response",
            "SEARCH_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
    return payload


async def _http_text(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout_s: int = 20,
) -> str:
    decision = get_sandbox_policy().check_url(url)
    if not decision.allowed:
        raise WebSearchError(
            f"sandbox blocked search URL: {decision.reason}",
            "SEARCH_URL_BLOCKED",
        )
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    request_headers = {"User-Agent": "PrometheaAgent/1.0", **(headers or {})}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, headers=request_headers, json=body) as response:
                text = await response.text(errors="replace")
                if response.status >= 400:
                    raise WebSearchError(
                        f"search provider returned HTTP {response.status}",
                        "SEARCH_PROVIDER_HTTP_ERROR",
                        retryable=response.status == 429 or response.status >= 500,
                        details={"status": response.status},
                    )
                return text
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError as exc:
        raise WebSearchError("search provider timed out", "SEARCH_TIMEOUT", retryable=True) from exc
    except WebSearchError:
        raise
    except aiohttp.ClientError as exc:
        raise WebSearchError(
            f"search provider request failed: {exc}",
            "SEARCH_PROVIDER_UNAVAILABLE",
            retryable=True,
        ) from exc


def _clean_text(value: Any) -> str:
    text = re.sub(r"<.*?>", "", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _result(title: Any, url: Any, snippet: Any = "", source: Any = "", published_at: Any = "") -> Dict[str, Any]:
    row = {
        "title": _clean_text(title),
        "url": str(url or "").strip(),
        "snippet": _clean_text(snippet),
        "source": _clean_text(source),
    }
    published = _clean_text(published_at)
    if published:
        row["published_at"] = published
    return row


def _compact_results(rows: Iterable[Dict[str, Any]], max_results: int) -> tuple[List[Dict[str, Any]], bool]:
    compact: List[Dict[str, Any]] = []
    seen: set[str] = set()
    truncated = False
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if len(compact) >= max_results:
            truncated = True
            break
        compact.append(row)
    return compact, truncated


def _search_payload(
    query: str,
    provider: str,
    rows: Iterable[Dict[str, Any]],
    max_results: int,
    *,
    content: str = "",
) -> Dict[str, Any]:
    results, truncated = _compact_results(rows, max_results)
    payload: Dict[str, Any] = {
        "query": query,
        "provider": provider,
        "count": len(results),
        "results": results,
        "truncated": truncated,
    }
    if content:
        payload["content"] = content
    return payload


class BraveSearchProvider(WebSearchProvider):
    provider_id = "brave"
    label = "Brave Search"
    requires_key = True
    priority = 10

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.get("brave_api_key"))

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": max_results}
        )
        payload = await _http_json(url, headers={"X-Subscription-Token": settings.get("brave_api_key")})
        rows = (
            _result(item.get("title"), item.get("url"), item.get("description"), item.get("profile", {}).get("name"))
            for item in ((payload.get("web") or {}).get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, rows, max_results)


class TavilySearchProvider(WebSearchProvider):
    provider_id = "tavily"
    label = "Tavily"
    requires_key = True
    priority = 20

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.get("tavily_api_key"))

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        payload = await _http_json(
            "https://api.tavily.com/search",
            method="POST",
            body={
                "api_key": settings.get("tavily_api_key"),
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
        )
        rows = (
            _result(item.get("title"), item.get("url"), item.get("content"), "Tavily")
            for item in (payload.get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, rows, max_results)


class SerpApiSearchProvider(WebSearchProvider):
    provider_id = "serpapi"
    label = "SerpAPI"
    requires_key = True
    priority = 30

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.get("serpapi_api_key"))

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"engine": "google", "q": query, "num": max_results, "api_key": settings.get("serpapi_api_key")}
        )
        payload = await _http_json(url)
        rows = (
            _result(item.get("title"), item.get("link"), item.get("snippet"), item.get("source"))
            for item in (payload.get("organic_results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, rows, max_results)


class SearxngSearchProvider(WebSearchProvider):
    provider_id = "searxng"
    label = "SearXNG"
    priority = 40

    def is_available(self, settings: WebSearchSettings) -> bool:
        return bool(settings.get("searxng_url"))

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        base = settings.get("searxng_url").rstrip("/")
        if not (base.startswith("http://") or base.startswith("https://")):
            raise WebSearchError(
                "SEARCH__SEARXNG_URL must start with http:// or https://",
                "SEARCH_PROVIDER_CONFIG_INVALID",
            )
        url = base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        payload = await _http_json(url)
        rows = (
            _result(item.get("title"), item.get("url"), item.get("content"), item.get("engine"))
            for item in (payload.get("results") or [])
            if isinstance(item, dict)
        )
        return _search_payload(query, self.provider_id, rows, max_results)


class DuckDuckGoSearchProvider(WebSearchProvider):
    provider_id = "duckduckgo"
    label = "DuckDuckGo"
    priority = 1000
    fallback = True

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        _ = settings
        endpoint = f"https://duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        page = await _http_text(endpoint)
        rows: List[Dict[str, Any]] = []
        for match in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = html.unescape(match.group(1)).strip()
            title = _clean_text(match.group(2))
            if href:
                rows.append(_result(title, href, "", "DuckDuckGo"))
        return _search_payload(query, self.provider_id, rows, max_results)


class WebSearchRuntime:
    """Provider-neutral web search capability used by the single public tool."""

    def __init__(self, providers: Optional[Iterable[WebSearchProvider]] = None) -> None:
        self._providers: Dict[str, WebSearchProvider] = {}
        for provider in providers or ():
            self.register_provider(provider)

    def register_provider(self, provider: WebSearchProvider) -> None:
        provider_id = str(provider.provider_id or "").strip().lower()
        if not provider_id:
            raise WebSearchError("web search provider id is required", "SEARCH_PROVIDER_INVALID")
        if provider_id in self._providers:
            raise WebSearchError(
                f'web search provider "{provider_id}" is already registered',
                "SEARCH_PROVIDER_DUPLICATE",
            )
        self._providers[provider_id] = provider

    def unregister_provider(self, provider_id: str) -> None:
        self._providers.pop(str(provider_id or "").strip().lower(), None)

    def provider_status(self, settings: WebSearchSettings) -> List[Dict[str, Any]]:
        return [
            {
                "id": provider.provider_id,
                "label": provider.label,
                "available": provider.is_available(settings),
                "requires_key": provider.requires_key,
                "fallback": provider.fallback,
            }
            for provider in self._ordered_providers(settings)
        ]

    async def search(self, query: str, max_results: int, settings: WebSearchSettings) -> Dict[str, Any]:
        selected = (settings.provider or "auto").strip().lower()
        fallback_policy = (settings.fallback_policy or "fallback").strip().lower()
        if fallback_policy not in {"strict", "fallback"}:
            raise WebSearchError(
                f'unsupported search fallback policy "{fallback_policy}"',
                "SEARCH_PROVIDER_CONFIG_INVALID",
            )
        if selected != "auto" and selected not in self._providers:
            raise WebSearchError(
                f'configured search provider "{selected}" is not registered',
                "SEARCH_PROVIDER_CONFIGURED_MISSING",
                details={"provider": selected},
            )

        errors: List[Dict[str, Any]] = []
        if selected != "auto" and not self._providers[selected].is_available(settings):
            errors.append(
                {
                    "provider": selected,
                    "code": "SEARCH_PROVIDER_CONFIGURED_UNAVAILABLE",
                    "error": f'configured search provider "{selected}" is unavailable',
                    "retryable": False,
                }
            )
        candidates = self._provider_order(selected, settings)
        if not candidates:
            raise WebSearchError(
                "no usable web search provider is registered",
                "SEARCH_PROVIDER_UNAVAILABLE",
                details={"configured_provider": selected, "provider_errors": errors},
            )

        for index, provider in enumerate(candidates):
            try:
                payload = await provider.search(query, max_results, settings)
                payload["configured_provider"] = selected
                payload["fallback_used"] = index > 0 or (selected != "auto" and provider.provider_id != selected)
                if errors:
                    payload["provider_errors"] = errors
                return payload
            except asyncio.CancelledError:
                raise
            except WebSearchError as exc:
                errors.append(
                    {
                        "provider": provider.provider_id,
                        "code": exc.code,
                        "error": str(exc),
                        "retryable": exc.retryable,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "provider": provider.provider_id,
                        "code": "SEARCH_PROVIDER_ERROR",
                        "error": str(exc),
                        "retryable": False,
                    }
                )

        raise WebSearchError(
            "all eligible web search providers failed",
            "SEARCH_PROVIDER_ERROR",
            retryable=any(bool(item.get("retryable")) for item in errors),
            details={"configured_provider": selected, "provider_errors": errors},
        )

    def _provider_order(self, selected: str, settings: WebSearchSettings) -> List[WebSearchProvider]:
        providers = self._ordered_providers(settings)
        fallbacks = [provider for provider in providers if provider.fallback and provider.is_available(settings)]
        if selected != "auto":
            primary = self._providers[selected]
            eligible_primary = [primary] if primary.is_available(settings) else []
            if settings.fallback_policy.strip().lower() == "strict":
                return eligible_primary
            candidates = [*eligible_primary, *(provider for provider in fallbacks if provider.provider_id != primary.provider_id)]
            return candidates
        candidates = [provider for provider in providers if provider.is_available(settings)]
        return candidates[:1] if settings.fallback_policy.strip().lower() == "strict" else candidates

    def _ordered_providers(self, settings: WebSearchSettings) -> List[WebSearchProvider]:
        configured_order = {provider_id: index for index, provider_id in enumerate(settings.provider_order)}
        return sorted(
            self._providers.values(),
            key=lambda item: (configured_order.get(item.provider_id, len(configured_order) + item.priority), item.provider_id),
        )


def build_default_web_search_runtime() -> WebSearchRuntime:
    """Compose the providers shipped by Promethea without coupling selection to construction order."""
    return WebSearchRuntime(
        providers=(
            BraveSearchProvider(),
            TavilySearchProvider(),
            SerpApiSearchProvider(),
            SearxngSearchProvider(),
            DuckDuckGoSearchProvider(),
        )
    )
