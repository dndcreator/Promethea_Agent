"""Bounded HTTP I/O shared by web capabilities, with per-hop and DNS policy checks."""
from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp


@dataclass(frozen=True)
class HttpDocument:
    url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes


class _BlockedAddress(PermissionError):
    pass


class _Resolver(aiohttp.abc.AbstractResolver):
    def __init__(self, *, allow_private):
        self.delegate = aiohttp.ThreadedResolver()
        self.allow_private = allow_private

    async def resolve(self, host, port=0, family=0):
        rows = await self.delegate.resolve(host, port, family)
        if not self.allow_private:
            for row in rows:
                ip = ipaddress.ip_address(row["host"])
                if not ip.is_global or ip.is_multicast:
                    raise _BlockedAddress("sandbox blocked a private or reserved DNS address")
        return rows

    async def close(self):
        await self.delegate.close()


async def request_document(url, *, policy, method="GET", headers=None, body=None,
                           timeout_s=20, max_bytes=4_000_000, service_url=None,
                           same_origin=False):
    def origin(value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("only http/https URLs without credentials are supported")
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)

    initial = origin(url)
    async with asyncio.timeout(timeout_s):
        for hop in range(6):
            current_origin = origin(url)
            if same_origin and current_origin != initial:
                raise PermissionError("cross-origin provider redirect is not allowed")
            decision = policy.check_service_url(url, service_url=service_url) if service_url else policy.check_url(url)
            if not decision.allowed:
                raise PermissionError(f"sandbox blocked url: {decision.reason}")
            enforced = getattr(policy, "is_enforced", lambda: True)()
            explicit_service = service_url and policy.is_service_url_allowed(url, service_url)
            resolver = _Resolver(allow_private=not enforced or not getattr(policy, "block_private_network", True) or bool(explicit_service))
            connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
            try:
                async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=timeout_s),
                                                 cookie_jar=aiohttp.DummyCookieJar(), trust_env=False) as session:
                    async with session.request(method, url, headers=headers, json=body, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                            if hop == 5:
                                raise ValueError("too many HTTP redirects")
                            url = urljoin(str(response.url), response.headers["Location"])
                            if response.status == 303 or response.status in {301, 302} and method == "POST":
                                method, body = "GET", None
                            continue
                        chunks, size = [], 0
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("HTTP response exceeds byte limit")
                            chunks.append(chunk)
                        return HttpDocument(str(response.url), response.status, response.headers.get("Content-Type", ""), response.charset, b"".join(chunks))
            except aiohttp.ClientConnectorError as exc:
                if isinstance(exc.os_error, _BlockedAddress):
                    raise PermissionError("sandbox blocked a private or reserved DNS address") from exc
                raise
            finally:
                await resolver.close()
    raise RuntimeError("HTTP request did not complete")
