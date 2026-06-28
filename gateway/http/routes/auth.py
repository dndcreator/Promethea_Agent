import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from loguru import logger
from neo4j.exceptions import AuthError, ServiceUnavailable

from ..schemas import (
    ChannelBindRequest,
    UserDeleteRequest,
    UserConfigUpdate,
    UserLogin,
    UserRegister,
)
from ..user_manager import user_manager
from ..config_compat import build_user_config_payload
from config import config
from gateway.user_secrets import get_user_secrets_status
from gateway_integration import get_gateway_integration

router = APIRouter()

SECRET_KEY = os.getenv("AUTH__SECRET_KEY", "change-me-in-env")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30
SESSION_TOKEN_EXPIRE_MINUTES = 60 * 12
AUTH_COOKIE_NAME = os.getenv("AUTH__COOKIE_NAME", "promethea_auth")
AUTH_COOKIE_SECURE = str(os.getenv("AUTH__COOKIE_SECURE", "false")).lower() in {"1", "true", "yes", "on"}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


def create_access_token(data: dict, *, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


async def get_current_user_id(request: Request, token: str | None = Depends(oauth2_scheme)) -> str:
    middleware_user_id = getattr(request.state, "user_id", None)
    if middleware_user_id:
        return str(middleware_user_id)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        cookies = getattr(request, "cookies", {}) or {}
        token = cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception


@router.post("/auth/register")
async def register(user: UserRegister):
    user_id = user_manager.create_user(user.username, user.password, user.agent_name)
    if not user_id:
        can_register, reason = user_manager.can_register()
        if not can_register and reason in {
            "neo4j_user_backend_unavailable",
            "neo4j_unavailable",
            "neo4j_authentication_failed",
        }:
            messages = {
                "neo4j_authentication_failed": "Neo4j is reachable, but username/password authentication failed",
                "neo4j_unavailable": "Neo4j is configured as the user backend but is unavailable",
                "neo4j_user_backend_unavailable": "Neo4j is configured as the user backend but is unavailable",
            }
            raise HTTPException(
                status_code=503,
                detail={
                    "code": reason,
                    "message": messages.get(reason, "Neo4j user backend is unavailable"),
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "username_exists_or_system_error",
                "message": "Username exists or system error",
            },
        )
    return {"status": "success", "user_id": user_id, "message": "Register success"}


@router.post("/auth/login")
async def login(user: UserLogin, response: Response):
    try:
        db_user = user_manager.verify_user(user.username, user.password)
    except AuthError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "neo4j_authentication_failed",
                "message": "Neo4j is reachable, but username/password authentication failed",
            },
        )
    except ServiceUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "neo4j_unavailable",
                "message": "Neo4j is configured as the user backend but is unavailable",
            },
        )
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_id = db_user.get("user_id")
    remember_me = bool(getattr(user, "remember_me", True))
    token_minutes = ACCESS_TOKEN_EXPIRE_MINUTES if remember_me else SESSION_TOKEN_EXPIRE_MINUTES
    access_token = create_access_token(
        data={"sub": user_id, "username": db_user.get("username")},
        expires_minutes=token_minutes,
    )

    user_config = user_manager.get_user_config(user_id)
    agent_name = user_config.get("agent_name", db_user.get("agent_name", "Promethea"))
    system_prompt = user_config.get("system_prompt", db_user.get("system_prompt"))
    secrets_status = get_user_secrets_status(user_id)
    api_key_configured = bool((secrets_status.get("api") or {}).get("api_key_configured"))

    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        max_age=token_minutes * 60 if remember_me else None,
        path="/",
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user_id,
        "username": db_user.get("username"),
        "agent_name": agent_name,
        "system_prompt": system_prompt,
        "api_key_configured": api_key_configured,
        "warning": None if api_key_configured else "Please set API__API_KEY in your user secrets.env or root .env",
    }


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return {"status": "success"}


@router.get("/user/profile")
async def get_profile(user_id: str = Depends(get_current_user_id)):
    user_config = user_manager.get_user_config(user_id)
    secrets_status = get_user_secrets_status(user_id)
    api_key_configured = bool((secrets_status.get("api") or {}).get("api_key_configured"))
    user = user_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "agent_name": user_config.get("agent_name", user.get("agent_name")),
        "system_prompt": user_config.get("system_prompt", user.get("system_prompt")),
        "api_key_configured": api_key_configured,
        "warning": None if api_key_configured else "Please set API__API_KEY in your user secrets.env or root .env",
    }


def _get_config_service():
    integration = get_gateway_integration()
    if not integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    gateway_server = integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return gateway_server.config_service


@router.post("/user/config")
async def update_config(
    req: UserConfigUpdate,
    user_id: str = Depends(get_current_user_id),
):
    payload = build_user_config_payload(req)
    try:
        config_service = _get_config_service()
        result = await config_service.update_user_config(user_id, payload, validate=True)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message", "Update config failed"))

        sanitized = dict(result.get("config") or {})
        if isinstance(sanitized.get("api"), dict):
            for key in ("api_key", "base_url", "model", "failover_models"):
                sanitized["api"].pop(key, None)
        if isinstance(sanitized.get("memory"), dict):
            mem = sanitized["memory"]
            if isinstance(mem.get("api"), dict):
                for key in ("api_key", "base_url", "model", "use_main_api"):
                    mem["api"].pop(key, None)
            if isinstance(mem.get("neo4j"), dict):
                for key in ("enabled", "uri", "username", "password", "database"):
                    mem["neo4j"].pop(key, None)
            for key in ("store_backend", "sqlite_graph_path", "flat_memory_path"):
                mem.pop(key, None)

        return {
            "status": "success",
            "message": result.get("message", "Config updated"),
            "deprecated": True,
            "canonical_endpoint": "/api/config/update",
            "config": sanitized,
        }
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        # Fallback: keep legacy behavior if gateway services are unavailable.
        graph_sync_ok = user_manager.update_user_config(
            user_id,
            agent_name=req.agent_name,
            system_prompt=req.system_prompt,
        )
        file_ok = user_manager.update_user_config_file(user_id, payload) if payload else True
        if not file_ok:
            raise HTTPException(status_code=500, detail="Update config failed")
        return {
            "status": "success",
            "message": "Config updated (legacy fallback)",
            "graph_sync_ok": graph_sync_ok,
            "deprecated": True,
            "canonical_endpoint": "/api/config/update",
        }


@router.post("/user/channels/bind")
async def bind_channel(
    request: ChannelBindRequest,
    user_id: str = Depends(get_current_user_id),
):
    success = user_manager.bind_channel_account(user_id, request.channel, request.account_id)
    if not success:
        raise HTTPException(status_code=500, detail="Bind failed")
    return {"status": "success", "message": f"bound {request.channel}"}


@router.get("/user/channels")
async def get_channels(user_id: str = Depends(get_current_user_id)):
    channels = user_manager.get_bound_channels(user_id)
    return {"status": "success", "channels": channels}


@router.post("/user/delete")
async def delete_user_account(
    req: UserDeleteRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")

    # Best-effort clear in-memory/persisted chat sessions for this user.
    try:
        from gateway.http.message_manager import message_manager

        sessions = message_manager.get_all_sessions_info(user_id=user_id)
        for sid in list(sessions.keys()):
            raw_sid = sid.split("::", 1)[-1] if "::" in sid else sid
            message_manager.delete_session(raw_sid, user_id=user_id)
    except Exception as e:
        logger.warning("user delete: failed to clear session cache for {}: {}", user_id, e)

    try:
        gateway = get_gateway_integration().gateway_server
        workflow_engine = getattr(gateway, "workflow_engine", None)
        purge = getattr(workflow_engine, "purge_user_state", None) if workflow_engine else None
        if callable(purge):
            purge(user_id)
        config_service = getattr(gateway, "config_service", None)
        cache = getattr(config_service, "_user_config_cache", None) if config_service else None
        if isinstance(cache, dict):
            cache.pop(user_id, None)
            cache.pop(user_id.replace("user_", "", 1), None)
    except Exception as e:
        logger.warning("user delete: failed to clear runtime user state for {}: {}", user_id, e)

    success = user_manager.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="Delete user failed")
    return {"status": "success", "message": "User account deleted"}
