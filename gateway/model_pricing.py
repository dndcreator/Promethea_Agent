"""Best-effort model-I/O pricing, independent of Agent decisions and billing."""
from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelRate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    base_url: str
    model: str
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    cache_read_per_million: Decimal | None = Field(default=None, ge=0)


class PricingSettings(BaseSettings):
    auto_refresh: bool = True
    cache_ttl_s: int = Field(default=3600, ge=60, le=86400)
    request_timeout_s: float = Field(default=2, ge=0.1, le=10)
    rates: list[ModelRate] = Field(default_factory=list, max_length=200)
    model_config = SettingsConfigDict(env_prefix="PRICING__", env_nested_delimiter="__", env_file=str(Path(__file__).resolve().parents[1] / ".env"), extra="ignore")

    @model_validator(mode="after")
    def unique_rates(self):
        for rate in self.rates:
            parsed = urlsplit(rate.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("pricing endpoint must not contain credentials, query or fragment")
        keys = [(rate.base_url.rstrip("/"), rate.model) for rate in self.rates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate endpoint/model pricing")
        return self


def _number(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _quote(base_url, model, rates, source, retrieved_at):
    fields = {"base_url": base_url, "model": model, "source": source, **rates}
    return {**fields, "retrieved_at": retrieved_at, "revision": hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]}


class ModelPricing:
    """Exact endpoint/model matching; bounded refresh, no LLM or guessed aliases."""
    catalog_url = "https://openrouter.ai/api/v1/models"
    endpoint = "https://openrouter.ai/api/v1"

    def __init__(self, settings=None, *, clock=time.time):
        self.settings = settings or PricingSettings()
        self.clock = clock
        self._quotes = {}
        self._expires = 0
        self._lock = asyncio.Lock()
        self._configured_at = self.clock()

    async def _fetch(self):
        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout_s)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(self.catalog_url, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError("pricing catalog unavailable")
                body = await response.content.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ValueError("pricing catalog exceeds limit")
                return json.loads(body)

    async def quote(self, base_url, model):
        base_url = str(base_url or "").rstrip("/")
        for rate in self.settings.rates:
            if rate.base_url.rstrip("/") == base_url and rate.model == model:
                rates = {"input": str(rate.input_per_million / 1_000_000), "output": str(rate.output_per_million / 1_000_000),
                         "cache_read": str(rate.cache_read_per_million / 1_000_000) if rate.cache_read_per_million is not None else None}
                return _quote(base_url, model, rates, "operator_env", self._configured_at)
        if base_url != self.endpoint or not self.settings.auto_refresh:
            return None
        async with self._lock:
            now = self.clock()
            if now >= self._expires:
                try:
                    data = await self._fetch()
                    rows = data["data"]
                    if not isinstance(rows, list) or len(rows) > 10000:
                        raise ValueError("invalid pricing catalog")
                    quotes = {}
                    for row in rows:
                        pricing = row.get("pricing") or {}
                        # Per-request, modality, provider-route or scheduled rates
                        # cannot be reconstructed from plain text token totals.
                        if pricing.get("overrides") or any(_number(value) != 0 for key, value in pricing.items() if key not in {"prompt", "completion", "input_cache_read"}):
                            continue
                        prompt, completion = _number(pricing.get("prompt")), _number(pricing.get("completion"))
                        cached = _number(pricing["input_cache_read"]) if "input_cache_read" in pricing else None
                        if prompt is None or completion is None or ("input_cache_read" in pricing and cached is None):
                            continue
                        identity = row.get("id")
                        if not isinstance(identity, str) or not identity or len(identity) > 300:
                            continue
                        quotes[identity] = _quote(base_url, identity, {"input": str(prompt), "output": str(completion), "cache_read": str(cached) if cached is not None else None}, self.catalog_url, now)
                    self._quotes = quotes
                    self._expires = now + self.settings.cache_ttl_s
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Expired quotes are not silently reused; throttle offline retries.
                    self._quotes = {}
                    self._expires = now + min(60, self.settings.cache_ttl_s)
        result = self._quotes.get(model)
        return dict(result) if result else None


def estimate(quote, usage):
    """Return unknown rather than a partial, guessed or multimodal token price."""
    if not quote:
        return None
    prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if any(type(value) is not int or value < 0 for value in (prompt, output)):
        return None
    cached = usage.get("prompt_cache_hit_tokens")
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        return None
    if cached is None:
        cached = details.get("cached_tokens")
    if quote.get("cache_read") is not None and cached is None:
        return None
    cached = cached or 0
    if type(cached) is not int or not 0 <= cached <= prompt or (cached and quote.get("cache_read") is None):
        return None
    rates = [_number(quote.get("input")), _number(quote.get("output")), _number(quote.get("cache_read") or 0)]
    if any(value is None for value in rates):
        return None
    value = (prompt - cached) * rates[0] + output * rates[1] + cached * rates[2]
    amount = float(value)
    return {"estimated_usd": amount, "pricing": dict(quote)} if math.isfinite(amount) else None


_pricing = None


async def quote_model(base_url, model):
    global _pricing
    try:
        if _pricing is None:
            _pricing = ModelPricing()
        return await _pricing.quote(base_url, model)
    except asyncio.CancelledError:
        raise
    except Exception:
        return None
