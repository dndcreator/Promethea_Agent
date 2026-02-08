from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional, Dict
from api_server.schemas import UserLogin, UserRegister, UserConfigUpdate, ChannelBindRequest
from api_server.user_manager import user_manager
from loguru import logger

router = APIRouter()

# 配置
SECRET_KEY = "promethea-local-secret-key"  # 本地部署使用固定Key即可
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30天过期

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    """依赖注入：获取当前用户ID"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
        raise HTTPException(status_code=400, detail="用户名已存在或系统错误")
    return {"status": "success", "user_id": user_id, "message": "注册成功"}

@router.post("/auth/login")
async def login(user: UserLogin):
    db_user = user_manager.verify_user(user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    user_id = db_user.get('user_id')
    access_token = create_access_token(data={"sub": user_id, "username": db_user.get('username')})
    
    # 尝试加载用户配置以返回最新的 agent_name
    user_config = user_manager.get_user_config(user_id)
    agent_name = user_config.get('agent_name', db_user.get('agent_name', 'Promethea'))
    system_prompt = user_config.get('system_prompt', db_user.get('system_prompt'))

    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "user_id": user_id,
        "username": db_user.get('username'),
        "agent_name": agent_name,
        "system_prompt": system_prompt
    }

@router.get("/user/profile")
async def get_profile(user_id: str = Depends(get_current_user_id)):
    # 优先从文件读取配置
    user_config = user_manager.get_user_config(user_id)
    
    # 兜底从 DB 读取
    user = user_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return {
        "user_id": user.get('user_id'),
        "username": user.get('username'),
        "agent_name": user_config.get('agent_name', user.get('agent_name')),
        "system_prompt": user_config.get('system_prompt', user.get('system_prompt')),
        "api": user_config.get('api', {})
    }

@router.post("/user/config")
async def update_config(config: UserConfigUpdate, user_id: str = Depends(get_current_user_id)):
    # 更新配置
    update_data = {}
    if config.agent_name is not None:
        update_data['agent_name'] = config.agent_name
    if config.system_prompt is not None:
        update_data['system_prompt'] = config.system_prompt
    if config.api is not None:
        update_data['api'] = config.api.dict(exclude_unset=True)

    success = user_manager.update_user_config(
        user_id, 
        agent_name=config.agent_name, 
        system_prompt=config.system_prompt
    )
    
    # 额外更新文件中的 API 配置
    if config.api:
        user_manager.update_user_config_file(user_id, {'api': config.api.dict(exclude_unset=True)})

    if not success:
        raise HTTPException(status_code=500, detail="更新配置失败")
    return {"status": "success", "message": "配置已更新"}

@router.post("/user/channels/bind")
async def bind_channel(request: ChannelBindRequest, user_id: str = Depends(get_current_user_id)):
    success = user_manager.bind_channel_account(user_id, request.channel, request.account_id)
    if not success:
        raise HTTPException(status_code=500, detail="绑定失败")
    return {"status": "success", "message": f"已绑定 {request.channel} 账号"}

@router.get("/user/channels")
async def get_channels(user_id: str = Depends(get_current_user_id)):
    channels = user_manager.get_bound_channels(user_id)
    return {"status": "success", "channels": channels}
