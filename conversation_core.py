from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI, OpenAI

from agentkit.mcp.tool_call import tool_call_loop
from config import config
from gateway.multimodal_service import ModelEndpoint, multimodal_service
from gateway.user_secrets import resolve_llm_runtime_settings, resolve_multimodal_runtime_settings


def _record_llm_metrics(duration: float, usage: Optional[Dict[str, Any]] = None) -> None:
    """Best-effort runtime metrics hook; never let observability break chat."""
    try:
        from gateway.http.metrics import get_metrics_collector

        usage = usage or {}
        get_metrics_collector().record_llm_call(
            duration=duration,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
    except Exception as exc:
        logger.debug("failed to record LLM metrics: {}", exc)


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

    def prepare_messages(self, messages: List[Dict]) -> List[Dict]:
        return self._inject_system_prompt(messages)

    def _inject_system_prompt(self, messages: List[Dict]) -> List[Dict]:
        system_prompt = (
            "You are Promethea, an assistant that can call tools.\n"
            "When you need tools, output only one strict JSON object and no prose in that assistant turn.\n"
            "For action turns, use a lightweight ReAct loop: Action, runtime Observation, then minimal verification before claiming success.\n"
            "Use keys: tool_name, agentType, service_name, and args (object). "
            "For official built-in tools use agentType=\"local\" and service_name equal to tool_name.\n"
            "Never write fake function syntax such as math.calculate(...), web_search(...), or file_create(...). "
            "Never claim a tool ran unless a runtime observation/result is present. "
            "Use only tools declared by the runtime tool block for this turn."
        )

        new_messages = list(messages)
        if new_messages and new_messages[0].get("role") == "system":
            new_messages[0]["content"] = f"{new_messages[0].get('content', '')}\n\n{system_prompt}"
        else:
            new_messages.insert(0, {"role": "system", "content": system_prompt})

        return new_messages

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip() or "default_user"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
        return safe[:128] or "default_user"

    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: str = None,
        user_id: Optional[str] = None,
        tool_executor=None,
        confirmation_resolver=None,
        max_recursion: Optional[int] = None,
        initial_response: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        messages_with_tools = self._inject_system_prompt(messages)
        llm_caller = lambda msgs: self.call_llm(msgs, user_config, user_id=user_id)

        final_response = await tool_call_loop(
            messages=messages_with_tools,
            llm_caller=llm_caller,
            is_streaming=False,
            max_recursion=max_recursion,
            session_id=session_id,
            tool_executor=tool_executor,
            confirmation_resolver=confirmation_resolver,
            initial_response=initial_response,
        )

        return final_response

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
                started = time.perf_counter()
                resp = await client.chat.completions.create(
                    model=endpoint.model,
                    messages=route_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )

                content = ""
                if resp.choices and len(resp.choices) > 0:
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
                _record_llm_metrics(time.perf_counter() - started, usage)

                result = {
                    "content": content,
                    "status": "success",
                    "model_used": endpoint.model,
                    "model_route": endpoint.source,
                    "model_attempts": attempts,
                    "usage": usage,
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
            try:
                client = self._resolve_async_client(user_config, endpoint.api_key, endpoint.base_url)
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
                async for chunk in stream:
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage:
                        usage = {
                            "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                            "completion_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
                        }
                    if chunk.choices and chunk.choices[0].delta.content:
                        if not first_token_recorded:
                            _record_llm_first_token_metrics(time.perf_counter() - started)
                            first_token_recorded = True
                        yield chunk.choices[0].delta.content
                _record_llm_metrics(time.perf_counter() - started, usage)
                return
            except Exception as e:
                err = str(e)
                errors.append(f"{endpoint.model}: {err}")
                if endpoint.source == "main" and modalities and multimodal_service.is_unsupported_modality_error(e):
                    multimodal_service.mark_unsupported(endpoint, modalities)
                    allow_multimodal_fallback = True
                logger.warning("LLM streaming failed on model '{}' via '{}': {}", endpoint.model, endpoint.source, err)

        error_message = "; ".join(errors) if errors else "unknown error"
        logger.error("LLM streaming call failed on all models: {}", error_message)
        yield f"[error] {error_message}"




