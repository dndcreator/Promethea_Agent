from __future__ import annotations

import os
import inspect
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI, OpenAI

from config import config
from gateway.multimodal_service import ModelEndpoint, multimodal_service
from gateway.user_secrets import resolve_llm_runtime_settings, resolve_multimodal_runtime_settings


def _record_llm_metrics(duration: float, usage: Optional[Dict[str, Any]] = None, *, cost_estimate=None) -> None:
    """Best-effort runtime metrics hook; never let observability break chat."""
    try:
        from gateway.http.metrics import get_metrics_collector

        usage = usage or {}
        get_metrics_collector().record_llm_call(
            duration=duration,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_estimate=cost_estimate,
        )
    except Exception as exc:
        logger.debug("failed to record LLM metrics: {}", exc)


def _usage_cache_fields(raw):
    result = {}
    cached = getattr(raw, "prompt_cache_hit_tokens", None)
    if cached is not None:
        result["prompt_cache_hit_tokens"] = cached
    details = getattr(raw, "prompt_tokens_details", None)
    if details is not None:
        cached = details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", None)
        if cached is not None:
            result["prompt_tokens_details"] = {"cached_tokens": cached}
    return result


async def _model_quote(endpoint, modalities):
    if modalities:
        return None
    from gateway.model_pricing import quote_model
    return await quote_model(endpoint.base_url, endpoint.model)


def _record_llm_first_token_metrics(duration: float) -> None:
    try:
        from gateway.http.metrics import get_metrics_collector

        get_metrics_collector().record_llm_first_token(duration=duration)
    except Exception as exc:
        logger.debug("failed to record LLM first-token metrics: {}", exc)


def _loggable_message_content(value: Any) -> str:
    if not isinstance(value, list):
        return str(value or "")
    parts: List[str] = []
    for part in value:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "text":
            parts.append(str(part.get("text") or ""))
        elif part_type in {"image", "image_url", "input_image"}:
            parts.append("[image input omitted]")
        elif part_type in {"audio", "input_audio"}:
            parts.append("[audio input omitted]")
        elif part_type in {"video", "input_video"}:
            parts.append("[video input omitted]")
        else:
            parts.append(f"[{part_type or 'structured'} input omitted]")
    return "\n".join(item for item in parts if item).strip()


class PrometheaConversation:
    def __init__(self):
        self.dev_mode = False
        self.client = self._build_sync_client(config.api.api_key, config.api.base_url)
        self.async_client = self._build_async_client(config.api.api_key, config.api.base_url)


    @staticmethod
    def _normalized_base_url(base_url: str) -> Optional[str]:
        text = str(base_url or "").strip()
        if not text:
            return None
        return text.rstrip("/") + "/"

    def _build_sync_client(self, api_key: str, base_url: str) -> OpenAI:
        kwargs: Dict[str, Any] = {"api_key": api_key or "placeholder-key-not-set"}
        normalized = self._normalized_base_url(base_url)
        if normalized:
            kwargs["base_url"] = normalized
        return OpenAI(**kwargs)

    def _build_async_client(self, api_key: str, base_url: str) -> AsyncOpenAI:
        kwargs: Dict[str, Any] = {"api_key": api_key or "placeholder-key-not-set"}
        normalized = self._normalized_base_url(base_url)
        if normalized:
            kwargs["base_url"] = normalized
        return AsyncOpenAI(**kwargs)

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip() or "default_user"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
        return safe[:128] or "default_user"

    def _get_client_params(
        self,
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ):
        runtime = resolve_llm_runtime_settings(user_id, behavior_config=user_config)
        return (
            runtime.get("api_key", ""),
            runtime.get("base_url", ""),
            runtime.get("model", ""),
            runtime.get("temperature", config.api.temperature),
            runtime.get("max_tokens", config.api.max_tokens),
            runtime.get("failover_models", []),
        )

    def _resolve_model_candidates(
        self,
        user_config: Optional[Dict[str, Any]],
        primary_model: str,
        runtime_failover_models: Optional[List[str]] = None,
    ) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def _push(value: Any) -> None:
            if not isinstance(value, str):
                return
            model_name = value.strip()
            if not model_name or model_name in seen:
                return
            seen.add(model_name)
            candidates.append(model_name)

        _push(primary_model)

        fallback_models = runtime_failover_models or getattr(config.api, "failover_models", []) or []

        if isinstance(fallback_models, list):
            for model_name in fallback_models:
                _push(model_name)

        return candidates

    def _resolve_async_client(self, user_config: Optional[Dict[str, Any]], api_key: str, base_url: str) -> AsyncOpenAI:
        if api_key != config.api.api_key or base_url != config.api.base_url:
            return self._build_async_client(api_key, base_url)
        return self.async_client

    async def call_llm(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict:
        api_key, base_url, model, temperature, max_tokens, failover_models = self._get_client_params(
            user_config,
            user_id=user_id,
        )
        model_candidates = self._resolve_model_candidates(user_config, model, failover_models)
        modalities = multimodal_service.detect_modalities(messages)
        dedicated = multimodal_service.dedicated_endpoint(
            resolve_multimodal_runtime_settings(user_id, behavior_config=user_config)
        )
        routes = [
            (ModelEndpoint(api_key=api_key, base_url=base_url, model=name), messages)
            for name in model_candidates
        ]
        if modalities:
            if dedicated is not None:
                routes.append((dedicated, messages))
            if model_candidates:
                routes.append((
                    ModelEndpoint(api_key=api_key, base_url=base_url, model=model_candidates[0], source="text_fallback"),
                    multimodal_service.strip_unsupported_parts(messages),
                ))
        errors: List[str] = []
        if not model_candidates:
            return {
                "content": "API call failed: API__MODEL is not configured in user secrets.env or root .env",
                "status": "error",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "model_used": None,
                "model_attempts": 0,
            }

        allow_multimodal_fallback = False
        attempts = 0
        for endpoint, route_messages in routes:
            if endpoint.source in {"multimodal", "text_fallback"} and not allow_multimodal_fallback:
                continue
            if endpoint.source == "main" and multimodal_service.is_known_unsupported(endpoint, modalities):
                allow_multimodal_fallback = True
                errors.append(f"{endpoint.model}: cached unsupported modality")
                continue
            attempts += 1
            try:
                client = self._resolve_async_client(user_config, endpoint.api_key, endpoint.base_url)
                price_quote = await _model_quote(endpoint, modalities)
                started = time.perf_counter()
                resp = await client.chat.completions.create(
                    model=endpoint.model,
                    messages=route_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )

                content = ""
                finish_reason = None
                if resp.choices and len(resp.choices) > 0:
                    finish_reason = getattr(resp.choices[0], "finish_reason", None)
                    message = getattr(resp.choices[0], "message", None)
                    if message:
                        content = getattr(message, "content", "") or ""

                usage = {
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0)
                    if hasattr(resp, "usage") and resp.usage
                    else 0,
                    "completion_tokens": getattr(resp.usage, "completion_tokens", 0)
                    if hasattr(resp, "usage") and resp.usage
                    else 0,
                }
                usage.update(_usage_cache_fields(getattr(resp, "usage", None)))
                from gateway.model_pricing import estimate
                reported = getattr(resp, "usage", None)
                cost_estimate = estimate(price_quote, {**usage, "prompt_tokens": getattr(reported, "prompt_tokens", None), "completion_tokens": getattr(reported, "completion_tokens", None)})
                _record_llm_metrics(time.perf_counter() - started, usage, cost_estimate=cost_estimate)

                code = "MODEL_OUTPUT_LIMIT" if finish_reason == "length" else "MODEL_EMPTY_RESPONSE" if not content.strip() else None
                result = {
                    "content": content,
                    "status": "error" if code else "success",
                    "code": code,
                    "error": code,
                    "finish_reason": finish_reason,
                    "request_id": getattr(resp, "id", None),
                    "max_tokens": max_tokens,
                    "model_used": endpoint.model,
                    "model_route": endpoint.source,
                    "model_attempts": attempts,
                    "usage": usage,
                    "cost_estimate": cost_estimate,
                }

                try:
                    d = datetime.now().strftime("%Y-%m-%d")
                    t = datetime.now().strftime("%H:%M:%S")
                    user_log_dir = os.path.join(str(config.system.log_dir), self._safe_user_segment(user_id))
                    if not os.path.exists(user_log_dir):
                        os.makedirs(user_log_dir, exist_ok=True)

                    log_file = os.path.join(user_log_dir, f"{d}.log")
                    with open(log_file, "a", encoding="utf-8") as f:
                        last_user = next((m.get("content", "") for m in reversed(route_messages) if m.get("role") == "user"), "")
                        last_user = _loggable_message_content(last_user)
                        f.write(f"[{t}] USER: {last_user}\n")
                        f.write(f"[{t}] ASSISTANT ({endpoint.model}): {content}\n")
                        f.write("-" * 50 + "\n")
                except Exception as e:
                    logger.error(f"save conversation log failed: {e}")

                if attempts > 1 or endpoint.source != "main":
                    logger.warning(
                        "LLM route fallback succeeded: model '{}' via '{}' after {} attempts",
                        endpoint.model,
                        endpoint.source,
                        attempts,
                    )
                return result
            except Exception as e:
                err = str(e)
                errors.append(f"{endpoint.model}: {err}")
                if endpoint.source == "main" and modalities and multimodal_service.is_unsupported_modality_error(e):
                    multimodal_service.mark_unsupported(endpoint, modalities)
                    allow_multimodal_fallback = True
                logger.warning("LLM call failed on model '{}' via '{}': {}", endpoint.model, endpoint.source, err)

        error_message = "; ".join(errors) if errors else "unknown error"
        logger.error("LLM API call failed on all models: {}", error_message)
        return {
            "content": f"API call failed: {error_message}",
            "status": "error",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model_used": None,
            "model_attempts": attempts,
        }

    async def call_llm_stream(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        reasoning_sink: Optional[Callable[[str], Awaitable[None]]] = None,
        result_sink: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        api_key, base_url, model, temperature, max_tokens, failover_models = self._get_client_params(
            user_config,
            user_id=user_id,
        )
        model_candidates = self._resolve_model_candidates(user_config, model, failover_models)
        modalities = multimodal_service.detect_modalities(messages)
        dedicated = multimodal_service.dedicated_endpoint(
            resolve_multimodal_runtime_settings(user_id, behavior_config=user_config)
        )
        routes = [
            (ModelEndpoint(api_key=api_key, base_url=base_url, model=name), messages)
            for name in model_candidates
        ]
        if modalities:
            if dedicated is not None:
                routes.append((dedicated, messages))
            if model_candidates:
                routes.append((
                    ModelEndpoint(api_key=api_key, base_url=base_url, model=model_candidates[0], source="text_fallback"),
                    multimodal_service.strip_unsupported_parts(messages),
                ))
        errors: List[str] = []
        if not model_candidates:
            yield "[error] API__MODEL is not configured in user secrets.env or root .env"
            return

        allow_multimodal_fallback = False
        attempts = 0
        for endpoint, route_messages in routes:
            if endpoint.source in {"multimodal", "text_fallback"} and not allow_multimodal_fallback:
                continue
            if endpoint.source == "main" and multimodal_service.is_known_unsupported(endpoint, modalities):
                allow_multimodal_fallback = True
                errors.append(f"{endpoint.model}: cached unsupported modality")
                continue
            attempts += 1
            emitted_stream_content = False
            try:
                client = self._resolve_async_client(user_config, endpoint.api_key, endpoint.base_url)
                price_quote = await _model_quote(endpoint, modalities)
                started = time.perf_counter()
                try:
                    stream = await client.chat.completions.create(
                        model=endpoint.model,
                        messages=route_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                except Exception as stream_exc:
                    message = str(stream_exc).lower()
                    if "stream_options" not in message and "include_usage" not in message:
                        raise
                    stream = await client.chat.completions.create(
                        model=endpoint.model,
                        messages=route_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    )
                if attempts > 1 or endpoint.source != "main":
                    logger.warning(
                        "LLM stream route fallback succeeded: model '{}' via '{}' after {} attempts",
                        endpoint.model,
                        endpoint.source,
                        attempts,
                        )
                usage = {"prompt_tokens": 0, "completion_tokens": 0}
                first_token_recorded = False
                finish_reason = None
                provider_request_id = None
                content_chars = 0
                reasoning_chars = 0
                usage_reported = False
                async for chunk in stream:
                    provider_request_id = getattr(chunk, "id", None) or provider_request_id
                    if chunk.choices:
                        finish_reason = getattr(chunk.choices[0], "finish_reason", None) or finish_reason
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage:
                        usage_reported = type(getattr(chunk_usage, "prompt_tokens", None)) is int and type(getattr(chunk_usage, "completion_tokens", None)) is int
                        usage = {
                            "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                            "completion_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
                        }
                        usage.update(_usage_cache_fields(chunk_usage))
                    delta = chunk.choices[0].delta if chunk.choices else None
                    reasoning_delta = getattr(delta, "reasoning_content", None) if delta is not None else None
                    reasoning_chars += len(str(reasoning_delta or ""))
                    if reasoning_delta and reasoning_sink is not None:
                        emitted_stream_content = True
                        pending = reasoning_sink(str(reasoning_delta))
                        if inspect.isawaitable(pending):
                            await pending
                    if delta is not None and delta.content:
                        emitted_stream_content = True
                        content_chars += len(delta.content)
                        if not first_token_recorded:
                            _record_llm_first_token_metrics(time.perf_counter() - started)
                            first_token_recorded = True
                        yield delta.content
                from gateway.model_pricing import estimate
                cost_estimate = estimate(price_quote, usage) if usage_reported else None
                _record_llm_metrics(time.perf_counter() - started, usage, cost_estimate=cost_estimate)
                code = "MODEL_OUTPUT_LIMIT" if finish_reason == "length" else "MODEL_EMPTY_RESPONSE" if not content_chars else None
                result = {
                    "status": "error" if code else "success", "code": code,
                    "finish_reason": finish_reason, "request_id": provider_request_id,
                    "model_used": endpoint.model, "usage": usage, "max_tokens": max_tokens,
                    "content_chars": content_chars, "reasoning_chars": reasoning_chars,
                    "cost_estimate": cost_estimate,
                }
                if result_sink is not None:
                    await result_sink(result)
                if code:
                    yield f"[error] {code}"
                return
            except Exception as e:
                err = str(e)
                errors.append(f"{endpoint.model}: {err}")
                if emitted_stream_content:
                    if result_sink is not None:
                        await result_sink({"status": "error", "code": "MODEL_STREAM_INTERRUPTED", "error": err,
                                           "model_used": endpoint.model, "usage": usage, "max_tokens": max_tokens,
                                           "request_id": provider_request_id, "finish_reason": finish_reason})
                    yield f"[error] {err}"
                    return
                if endpoint.source == "main" and modalities and multimodal_service.is_unsupported_modality_error(e):
                    multimodal_service.mark_unsupported(endpoint, modalities)
                    allow_multimodal_fallback = True
                logger.warning("LLM streaming failed on model '{}' via '{}': {}", endpoint.model, endpoint.source, err)

        error_message = "; ".join(errors) if errors else "unknown error"
        logger.error("LLM streaming call failed on all models: {}", error_message)
        yield f"[error] {error_message}"




