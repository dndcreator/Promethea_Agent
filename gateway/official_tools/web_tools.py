from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentkit.security.sandbox import get_sandbox_policy
from gateway.capability_service import ToolInvocationContext
from gateway.user_secrets import resolve_search_runtime_settings

from .web_search_runtime import (
    WebSearchError,
    WebSearchRuntime,
    WebSearchSettings,
    build_default_web_search_runtime,
)


class WebFetchTextTool:
    tool_id = "web.fetch_text"
    side_effect_level = "read_only"
    name = "web.fetch_text"
    description = "Fetch text content from a web page (GET only)."
    official = True
    official_domain = "web"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        url = str((args or {}).get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("only http/https URLs are supported")
        decision = get_sandbox_policy().check_url(url)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked url: {decision.reason}")

        timeout_s = int((args or {}).get("timeout_s") or 15)
        timeout_s = max(3, min(timeout_s, 60))
        max_chars = int((args or {}).get("max_chars") or 50000)
        max_chars = max(1000, min(max_chars, 200000))
        user_agent = str((args or {}).get("user_agent") or "PrometheaAgent/1.0")

        req = urllib.request.Request(url, headers={"User-Agent": user_agent}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read(max_chars * 3)
            charset = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            content_type = str(resp.headers.get("Content-Type") or "")
            status = int(getattr(resp, "status", 200))

        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        else:
            truncated = False
        return {
            "url": url,
            "status": status,
            "content_type": content_type,
            "truncated": truncated,
            "text": text,
        }


class WebExtractLinksTool:
    tool_id = "web.extract_links"
    side_effect_level = "read_only"
    name = "web.extract_links"
    description = "Extract links from HTML text."
    official = True
    official_domain = "web"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        html = str((args or {}).get("html") or "")
        if not html:
            raise ValueError("html is required")
        max_results = int((args or {}).get("max_results") or 100)
        max_results = max(1, min(max_results, 500))
        links: List[str] = []
        for match in re.finditer(r"""href\s*=\s*["']([^"'#]+)["']""", html, flags=re.IGNORECASE):
            href = str(match.group(1) or "").strip()
            if not href:
                continue
            links.append(href)
            if len(links) >= max_results:
                break
        return {
            "count": len(links),
            "links": links,
        }


class WebFetchJsonTool:
    tool_id = "web.fetch_json"
    side_effect_level = "read_only"
    name = "web.fetch_json"
    description = "Fetch JSON from an HTTP endpoint."
    official = True
    official_domain = "web"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        url = str((args or {}).get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("only http/https URLs are supported")
        decision = get_sandbox_policy().check_url(url)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked url: {decision.reason}")

        timeout_s = int((args or {}).get("timeout_s") or 20)
        timeout_s = max(3, min(timeout_s, 60))
        user_agent = str((args or {}).get("user_agent") or "PrometheaAgent/1.0")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            payload = json.loads(text)
            status = int(getattr(resp, "status", 200))
        return {"url": url, "status": status, "data": payload}


class WebSearchTool:
    tool_id = "web.search"
    side_effect_level = "read_only"
    name = "web.search"
    description = "Search the web and return result links/snippets."
    official = True
    official_domain = "web"
    timeout_ms = 30000
    input_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "provider": {"type": "string"},
            "count": {"type": "integer"},
            "results": {"type": "array"},
            "truncated": {"type": "boolean"},
        },
        "required": ["query", "provider", "count", "results", "truncated"],
    }

    def __init__(self, *, runtime: Optional[WebSearchRuntime] = None, max_results: int = 8) -> None:
        self.runtime = runtime or build_default_web_search_runtime()
        self.max_results = max(1, min(int(max_results), 20))

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        user_id = str((ctx.user_id if ctx else "") or "").strip() or None
        resolved = resolve_search_runtime_settings(user_id)
        settings = WebSearchSettings(
            provider=resolved.get("provider") or "auto",
            fallback_policy=resolved.get("fallback_policy") or "fallback",
            provider_order=tuple(
                item.strip().lower()
                for item in str(resolved.get("provider_order") or "").split(",")
                if item.strip()
            ),
            values=resolved,
        )
        try:
            async with asyncio.timeout(self.timeout_ms / 1000):
                payload = await self.runtime.search(query, self.max_results, settings)
        except asyncio.TimeoutError as exc:
            raise WebSearchError("web search timed out", "SEARCH_TIMEOUT", retryable=True) from exc
        return payload

    @staticmethod
    def result_summary(result: Any) -> str:
        if not isinstance(result, dict):
            return "Web search completed"
        count = int(result.get("count") or 0)
        provider = str(result.get("provider") or "web")
        suffix = " after provider fallback" if result.get("fallback_used") else ""
        return f"Found {count} sources via {provider}{suffix}"

    @staticmethod
    def result_metadata(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        return {
            "kind": "web_search",
            "query": str(result.get("query") or ""),
            "provider": str(result.get("provider") or ""),
            "configured_provider": str(result.get("configured_provider") or ""),
            "count": int(result.get("count") or 0),
            "truncated": bool(result.get("truncated", False)),
            "fallback_used": bool(result.get("fallback_used", False)),
            "sources": [
                {
                    key: row[key]
                    for key in ("title", "url", "snippet", "source", "published_at")
                    if row.get(key) not in (None, "")
                }
                for row in (result.get("results") or [])[:20]
                if isinstance(row, dict)
            ],
        }


class WebDownloadToWorkspaceTool:
    tool_id = "web.download_to_workspace"
    side_effect_level = "workspace_write"
    name = "web.download_to_workspace"
    description = "Download URL content and save to workspace text file."
    official = True
    official_domain = "web"

    def __init__(self, *, workspace_service: Any) -> None:
        self.workspace_service = workspace_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        url = str((args or {}).get("url") or "").strip()
        path = str((args or {}).get("path") or "").strip()
        if not url:
            raise ValueError("url is required")
        if not path:
            raise ValueError("path is required")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("only http/https URLs are supported")
        decision = get_sandbox_policy().check_url(url)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked url: {decision.reason}")
        timeout_s = int((args or {}).get("timeout_s") or 20)
        timeout_s = max(3, min(timeout_s, 60))
        max_chars = int((args or {}).get("max_chars") or 200000)
        max_chars = max(1000, min(max_chars, 2_000_000))
        req = urllib.request.Request(url, headers={"User-Agent": "PrometheaAgent/1.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read(max_chars * 3)
            text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        text = text[:max_chars]
        user_id = str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip() or "default_user"
        workspace_id = str((args or {}).get("workspace_id") or (ctx.session_id if ctx else "") or "default").strip() or "default"
        handle = self.workspace_service.resolve_workspace_handle(user_id=user_id, workspace_id=workspace_id)
        root = Path(handle.root_path)
        target = (root / path).resolve()
        try:
            target.relative_to(root.resolve())
        except Exception as e:
            raise ValueError(f"path escapes workspace root: {path}") from e
        row = self.workspace_service.create_document(
            handle=handle,
            relative_path=str(target.relative_to(root)).replace("\\", "/"),
            content=text,
            requester_user_id=user_id,
        )
        row["source_url"] = url
        row["content_chars"] = len(text)
        return row
