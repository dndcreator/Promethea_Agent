from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...gateway_integration import get_gateway_integration

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    user_id: str
    config: Dict[str, Any]


class ConfigResetRequest(BaseModel):
    """配置重置请求"""
    user_id: str
    reset_to_default: bool = True


class ConfigSwitchModelRequest(BaseModel):
    """模型切换请求"""
    user_id: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@router.get("/config")
async def get_config(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    获取配置
    
    Args:
        user_id: 用户ID（可选，如果不提供则返回默认配置）
        
    Returns:
        合并后的配置字典
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    config_data = gateway_server.config_service.get_merged_config(user_id)
    return config_data


@router.post("/config/update")
async def update_config(request: ConfigUpdateRequest) -> Dict[str, Any]:
    """
    更新用户配置
    
    Args:
        request: 配置更新请求
        
    Returns:
        更新结果
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    result = await gateway_server.config_service.update_user_config(
        request.user_id,
        request.config
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("message", "Update failed"))
    
    return result


@router.post("/config/reset")
async def reset_config(request: ConfigResetRequest) -> Dict[str, Any]:
    """
    重置用户配置
    
    Args:
        request: 配置重置请求
        
    Returns:
        重置结果
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    result = await gateway_server.config_service.reset_user_config(
        request.user_id,
        request.reset_to_default
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("message", "Reset failed"))
    
    return result


@router.post("/config/switch-model")
async def switch_model(request: ConfigSwitchModelRequest) -> Dict[str, Any]:
    """
    切换模型（用户级）
    
    Args:
        request: 模型切换请求
        
    Returns:
        切换结果
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    result = await gateway_server.config_service.switch_model(
        request.user_id,
        request.model,
        request.api_key,
        request.base_url
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("message", "Switch model failed"))
    
    return result


@router.get("/config/diagnose")
async def diagnose_config(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    诊断配置问题
    
    Args:
        user_id: 用户ID（可选）
        
    Returns:
        诊断结果
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    result = gateway_server.config_service.diagnose_config(user_id)
    return result


@router.post("/config/reload")
async def reload_config() -> Dict[str, Any]:
    """
    重新加载默认配置（热重载）
    
    Returns:
        重载结果
    """
    gateway_integration = get_gateway_integration()
    if not gateway_integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    
    gateway_server = gateway_integration.get_gateway_server()
    if not gateway_server or not gateway_server.config_service:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    
    result = await gateway_server.config_service.reload_default_config()
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("message", "Reload failed"))
    
    return result
