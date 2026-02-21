from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jose import JWTError
from loguru import logger

from .routes.auth import decode_access_token
from .state import metrics
from gateway_integration import get_gateway_integration


@dataclass
class RateLimitConfig:
    requests: int = 120
    window_seconds: int = 60


class InMemoryRateLimiter:
    def __init__(self, cfg: RateLimitConfig):
        self.cfg = cfg
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        threshold = now - self.cfg.window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] < threshold:
                q.popleft()
            if len(q) >= self.cfg.requests:
                return False
            q.append(now)
            return True


def register_http_middlewares(app: FastAPI) -> None:
    integration = get_gateway_integration()
    rate_cfg = {}
    try:
        if integration and isinstance(integration.config, dict):
            rate_cfg = (
                ((integration.config.get("http") or {}).get("rate_limit") or {})
                if isinstance(integration.config, dict)
                else {}
            )
    except Exception:
        rate_cfg = {}

    limiter = InMemoryRateLimiter(
        RateLimitConfig(
            requests=int(
                os.getenv(
                    "GATEWAY_RATE_LIMIT_REQUESTS",
                    str(rate_cfg.get("requests", 120)),
                )
            ),
            window_seconds=int(
                os.getenv(
                    "GATEWAY_RATE_LIMIT_WINDOW_SECONDS",
                    str(rate_cfg.get("window_seconds", 60)),
                )
            ),
        )
    )
    public_paths = {
        "/api/auth/login",
        "/api/auth/register",
        "/api/status",
        "/api/metrics",
        "/health",
        "/gateway/status",
    }

    @app.middleware("http")
    async def request_context_and_auth(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.user_id = None

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            if token:
                try:
                    payload = decode_access_token(token)
                    request.state.user_id = payload.get("sub")
                except JWTError:
                    if request.url.path.startswith("/api") and request.url.path not in public_paths:
                        return JSONResponse(
                            status_code=401,
                            content={
                                "status": "error",
                                "error": {"code": "unauthorized", "message": "Invalid token"},
                                "request_id": request_id,
                            },
                        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api"):
            user_id = getattr(request.state, "user_id", None)
            ip = request.client.host if request.client else "unknown"
            key = str(user_id or ip)
            if not limiter.allow(key):
                return JSONResponse(
                    status_code=429,
                    content={
                        "status": "error",
                        "error": {"code": "rate_limited", "message": "Too many requests"},
                        "request_id": getattr(request.state, "request_id", None),
                    },
                )
        return await call_next(request)

    @app.middleware("http")
    async def logging_and_metrics(request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            try:
                metrics.record_http_request(
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=elapsed_ms,
                )
            except Exception:
                pass
            logger.info(
                "{} {} -> {} ({:.1f}ms) rid={}",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                getattr(request.state, "request_id", "-"),
            )

    @app.middleware("http")
    async def normalized_error_response(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            logger.exception("Unhandled request error: {}", e)
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "error": {"code": "internal_error", "message": str(e)},
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
