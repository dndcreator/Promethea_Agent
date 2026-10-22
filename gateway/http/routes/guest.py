"""Bounded, account-free text chat over the existing ConversationService."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from config import config
from gateway.public_contracts import GuestChatRequest, GuestChatResponse, GuestChatStatus
from ..dispatcher import get_gateway_server
from ..middleware import InMemoryRateLimiter, RateLimitConfig


router = APIRouter()


def _runtime(request: Request):
    gateway = get_gateway_server()
    config_service = getattr(gateway, "config_service", None)
    defaults = config_service.get_default_config() if config_service else config
    policy = defaults.guest_chat
    try:
        local = ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        local = False
    forwarded = any(request.headers.get(key) for key in ("forwarded", "x-forwarded-for", "x-real-ip"))
    origin = request.headers.get("origin")
    origin_allowed = True
    if origin:
        try:
            parsed = urlsplit(origin)
            origin_allowed = parsed.scheme in {"http", "https"} and parsed.hostname == request.url.hostname
            if not origin_allowed and local:
                origin_allowed = parsed.scheme in {"http", "https"} and (
                    parsed.hostname == "localhost" or ip_address(parsed.hostname or "").is_loopback
                )
        except ValueError:
            origin_allowed = False
    enabled = policy.enabled and (local or policy.allow_remote) and (policy.allow_remote or not forwarded) and origin_allowed
    service = getattr(gateway, "conversation_service", None)
    available = enabled and service is not None and bool(defaults.api.model)
    return defaults, service, enabled, available


def _error(status: int, code: str, message: str):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.get("/guest", response_model=GuestChatStatus)
async def guest_status(request: Request):
    defaults, _, enabled, available = _runtime(request)
    return GuestChatStatus(enabled=enabled, available=available, max_messages=defaults.guest_chat.max_messages,
                           max_input_chars=defaults.guest_chat.max_input_chars)


@router.post("/guest/chat", response_model=GuestChatResponse)
async def guest_chat(body: GuestChatRequest, request: Request):
    defaults, service, enabled, available = _runtime(request)
    if not enabled:
        raise _error(403, "GUEST_CHAT_DISABLED", "Guest chat is not enabled for this connection")
    if not available:
        raise _error(503, "GUEST_CHAT_UNAVAILABLE", "Guest chat is temporarily unavailable")
    policy = defaults.guest_chat
    if len(body.messages) > policy.max_messages or sum(len(item.content) for item in body.messages) > policy.max_input_chars:
        raise _error(413, "GUEST_INPUT_LIMIT", "The temporary conversation exceeds its input limit")
    if body.messages[-1].role != "user" or not body.messages[-1].content.strip():
        raise _error(422, "GUEST_INPUT_INVALID", "The last message must be a non-empty user message")

    # One bounded deployment-wide bucket per worker, not an unbounded visitor ledger.
    state = getattr(request.app.state, "guest_chat", None)
    if state is None:
        state = {"active": 0, "quota": policy.requests_per_minute,
                 "limiter": InMemoryRateLimiter(RateLimitConfig(requests=policy.requests_per_minute))}
        request.app.state.guest_chat = state
    if state["active"] >= policy.max_concurrent:
        raise _error(429, "GUEST_CHAT_BUSY", "Guest chat is busy; please retry shortly")
    if state["quota"] != policy.requests_per_minute:
        state["quota"] = policy.requests_per_minute
        state["limiter"] = InMemoryRateLimiter(RateLimitConfig(requests=policy.requests_per_minute))
    if not state["limiter"].allow("guest"):
        raise _error(429, "GUEST_RATE_LIMIT", "Guest chat has reached its request limit")

    prompt = service._append_language_policy(service._ensure_core_system_prompt(defaults.prompts.Promethea_system_prompt))
    messages = [{"role": "system", "content": prompt},
                {"role": "system", "content": 'Runtime scope: {"mode":"temporary_text_chat","tools":[],"memory":false,"files":false,"computer_control":false}'},
                *[item.model_dump() for item in body.messages]]
    behavior = {"api": {"max_tokens": min(defaults.api.max_tokens, policy.max_output_tokens)}}
    state["active"] += 1
    task = asyncio.create_task(service.call_llm(deepcopy(messages), user_config=behavior, user_id=None))
    try:
        async def wait_for_result():
            while not task.done():
                await asyncio.wait({task}, timeout=0.2)
                if await request.is_disconnected():
                    raise _error(499, "GUEST_CHAT_CANCELLED", "Request cancelled")
            return await task

        result = await asyncio.wait_for(wait_for_result(), timeout=policy.timeout_s)
        if not isinstance(result, dict) or result.get("status") != "success" or not str(result.get("content") or "").strip():
            raise _error(503, "GUEST_MODEL_UNAVAILABLE", "The model could not complete this reply")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        return GuestChatResponse(response=str(result["content"]), usage={
            key: int(usage[key]) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage.get(key), (int, float)) and usage[key] >= 0
        })
    except asyncio.TimeoutError:
        raise _error(504, "GUEST_CHAT_TIMEOUT", "The model did not reply in time")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Guest model request failed ({})", type(exc).__name__)
        raise _error(503, "GUEST_MODEL_UNAVAILABLE", "The model could not complete this reply")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        state["active"] -= 1
