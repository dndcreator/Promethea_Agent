"""One deterministic article extractor for HTTP and content-tool consumers."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from agentkit.security.http import request_document
from agentkit.security.sandbox import get_sandbox_policy


def decode_text(raw, charset=None):
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError:
        pass
    from trafilatura.utils import decode_file
    return decode_file(raw)


def extract_page(source, *, url, content_type="text/html", max_chars=50000, include_links=False):
    media = content_type.split(";", 1)[0].strip().lower()
    title, links = "", []
    if media in {"text/html", "application/xhtml+xml", ""}:
        from lxml import html
        from trafilatura import extract
        from trafilatura.settings import DEFAULT_CONFIG
        config = deepcopy(DEFAULT_CONFIG)
        config["DEFAULT"]["MAX_TREE_SIZE"] = "50000"
        tree = html.fromstring(source or "<html></html>")
        title = " ".join(tree.xpath("string(//title)").split())[:500]
        extracted = extract(source, url=url, output_format="json", with_metadata=True,
                            include_comments=False, include_tables=True, favor_precision=True,
                            config=config)
        data = json.loads(extracted) if extracted else {}
        text = data.get("text") or ""
        title = str(title or data.get("title") or "")[:500]
        if include_links:
            for href in tree.xpath("//a[@href]/@href"):
                link = urljoin(url, href)
                parsed = urlsplit(link)
                if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and link not in links:
                    links.append(link)
                    if len(links) == 50:
                        break
        method = "trafilatura"
    elif media.startswith("text/") or media in {"application/json", "application/xml"}:
        text, method = source, "plain_text"
    else:
        raise ValueError("unsupported web content type; use the appropriate document or browser capability")
    return {"title": title, "text": text[:max_chars], "truncated": len(text) > max_chars,
            "extraction_method": method, "read_status": "read" if text.strip() else "empty",
            "links": links, "content_sha256": hashlib.sha256(text[:max_chars].encode()).hexdigest()}


async def fetch_page(url, *, policy=None, timeout_s=20, max_chars=50000, user_agent="PrometheaAgent/1.0", include_links=False):
    started = time.monotonic()
    response = await request_document(url, policy=policy or get_sandbox_policy(), timeout_s=timeout_s,
                                      headers={"User-Agent": user_agent, "Accept": "text/html,text/plain,application/xhtml+xml"})
    if response.status >= 400:
        raise RuntimeError(f"web page returned HTTP {response.status}")
    decoded = decode_text(response.body, response.charset)
    result = await asyncio.to_thread(extract_page, decoded, url=response.url, content_type=response.content_type,
                                     max_chars=max_chars, include_links=include_links)
    result.update(url=url, final_url=response.url, status=response.status, content_type=response.content_type,
                  fetched_at=datetime.now(timezone.utc).timestamp(), elapsed_ms=int((time.monotonic() - started) * 1000),
                  evidence_kind="retrieved_page_not_verified_claims")
    result["source_id"] = hashlib.sha256((response.url + "\n" + result["content_sha256"]).encode()).hexdigest()
    return result
