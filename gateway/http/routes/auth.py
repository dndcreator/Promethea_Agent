import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from ..schemas import (
    ChannelBindRequest,
    UserDeleteRequest,
    UserConfigUpdate,
    UserLogin,
    UserRegister,
)
from ..user_manager import user_manager
from config import config

router = APIRouter()

SECRET_KEY = os.getenv("AUTH__SECRET_KEY", "change-me-in-env")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
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
        raise HTTPException(status_code=400, detail="Username exists or system error")
    return {"status": "success", "user_id": user_id, "message": "Register success"}


@router.post("/auth/login")
async def login(user: UserLogin):
    db_user = user_manager.verify_user(user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_id = db_user.get("user_id")
    access_token = create_access_token(
        data={"sub": user_id, "username": db_user.get("username")}
    )

    user_config = user_manager.get_user_config(user_id)
    agent_name = user_config.get("agent_name", db_user.get("agent_name", "Promethea"))
    system_prompt = user_config.get("system_prompt", db_user.get("system_prompt"))
    api_key_configured = bool(
        config.api.api_key and config.api.api_key != "placeholder-key-not-set"
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user_id,
        "username": db_user.get("username"),
        "agent_name": agent_name,
        "system_prompt": system_prompt,
        "api_key_configured": api_key_configured,
        "warning": None if api_key_configured else "Please set API__API_KEY in .env first",
    }


@router.get("/user/profile")
async def get_profile(user_id: str = Depends(get_current_user_id)):
    user_config = user_manager.get_user_config(user_id)
    api_key_configured = bool(
        config.api.api_key and config.api.api_key != "placeholder-key-not-set"
    )
    user = user_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "agent_name": user_config.get("agent_name", user.get("agent_name")),
        "system_prompt": user_config.get("system_prompt", user.get("system_prompt")),
        "api_key_configured": api_key_configured,
        "warning": None if api_key_configured else "Please set API__API_KEY in .env first",
    }


@router.post("/user/config")
async def update_config(
    req: UserConfigUpdate,
    user_id: str = Depends(get_current_user_id),
):
    update_data = {}
    if req.agent_name is not None:
        update_data["agent_name"] = req.agent_name
    if req.system_prompt is not None:
        update_data["system_prompt"] = req.system_prompt

    graph_sync_ok = user_manager.update_user_config(
        user_id,
        agent_name=req.agent_name,
        system_prompt=req.system_prompt,
    )

    file_ok = True
    if update_data:
        file_ok = user_manager.update_user_config_file(user_id, update_data)

    if not file_ok:
        raise HTTPException(status_code=500, detail="Update config failed")

    return {"status": "success", "message": "Config updated", "graph_sync_ok": graph_sync_ok}


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
    except Exception:
        pass

    success = user_manager.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="Delete user failed")
    return {"status": "success", "message": "User account deleted"}

